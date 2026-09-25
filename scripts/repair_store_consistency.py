#!/usr/bin/env python3
"""
OPS-04 (#52): the repair half of `check_store_consistency.py`. Three idempotent
actions over NEWS_L1/NEWS_L2 (FAISS), `chunks` and `articles`:

  1. orphans: a sitemap with no `articles` row that can never get one
     (crawl_status `rejected_filter`, fetch-failure cap reached, or the sitemap
     row is gone) loses its vectors AND its `chunks` rows, always together.
     RAG would otherwise keep returning both as hits with no article behind
     them (FAISS for semantic search, chunks.fts_vector for full-text search).
     Deleting only the vectors would leave chunk rows pointing at nothing. The
     first --apply on 2026-09-26 did exactly that for 2,918 VIVA sitemaps
     (June debris: SYS-08 failed their articles after their chunks were
     written), which is why the two now go together and a test pins it.
     A vector whose sitemap is still queued is NOT touched: when the crawl
     reaches it, `save_chunk_data` finds the vector by (sitemap, level, index)
     and links it (SYS-17's reuse path). Those are reported as `healing`.
  2. missing chunk rows: a vector whose sitemap HAS an article but no `chunks`
     row at its (sitemap, level, index) gets the row rebuilt from the
     docstore (page_content + metadata), linked to that vector's id.
  3. duplicate vectors: 2+ vectors for one (sitemap, level, index) key. The
     one a `chunks` row points at is kept (or the first, if none does); the
     rest are deleted.

Dry run by default: prints what each action would do. `--apply` writes. It first
copies NEWS_L1/NEWS_L2 to backups/faiss_<stamp>/, deletes through FAISS and saves
with the crawler's atomic save, then inserts chunk rows. It refuses to write
while a crawl is running (a `crawl_log` row still `started` in the last 4 h):
the crawl holds the index in memory, and its flush would undo the repair (DBT-10).

    python scripts/repair_store_consistency.py                 # dry run
    python scripts/repair_store_consistency.py --apply
"""
import argparse
import collections
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES, VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")


def docs_by_key(docstore_dict):
    """(sitemap_id, level, index) -> [doc_id, ...] for one index's docstore."""
    out = collections.defaultdict(list)
    for doc_id, doc in docstore_dict.items():
        m = doc.metadata
        if {"sitemap_id", "chunk_level", "chunk_index"} <= m.keys():
            out[(int(m["sitemap_id"]), int(m["chunk_level"]), int(m["chunk_index"]))].append(doc_id)
    return out


def plan(index_docs, sitemap_state, chunk_rows):
    """See _plan; adds `delete_chunk_sitemaps` -- terminal sitemaps that have
    chunk rows (with or without vectors left)."""
    p = _plan(index_docs, sitemap_state, chunk_rows)
    doomed = {k[0] for k in chunk_rows if sitemap_state.get(k[0], "terminal") == "terminal"}
    p["delete_chunk_sitemaps"] = doomed
    p["counts"]["orphan_chunk_rows_deleted"] = sum(1 for k in chunk_rows if k[0] in doomed)
    return p


def _plan(index_docs, sitemap_state, chunk_rows):
    """Pure. `index_docs`: {db_name: {key: [doc_id, ...]}}. `sitemap_state`:
    {sitemap_id: "article" | "queued" | "terminal"} (a missing id = row gone).
    `chunk_rows`: {key: embedding_id or None}.

    Returns {"delete": {db_name: [doc_id]}, "insert": [(db_name, key, doc_id)],
    "healing": set(sitemap_ids), "counts": {...}}."""
    delete = collections.defaultdict(list)
    insert, healing = [], set()
    counts = collections.Counter()
    for db_name, by_key in index_docs.items():
        for key, doc_ids in by_key.items():
            sid = key[0]
            state = sitemap_state.get(sid, "terminal")
            if state == "queued":
                healing.add(sid)
                continue
            if state == "terminal":
                delete[db_name].extend(doc_ids)
                counts["orphan_vectors_deleted"] += len(doc_ids)
                continue
            # state == "article": keep exactly one vector for the key
            linked = chunk_rows.get(key)
            keep = linked if linked in doc_ids else doc_ids[0]
            dupes = [d for d in doc_ids if d != keep]
            if dupes:
                delete[db_name].extend(dupes)
                counts["duplicate_vectors_deleted"] += len(dupes)
            if key not in chunk_rows:
                insert.append((db_name, key, keep))
                counts["chunk_rows_inserted"] += 1
    counts["healing_sitemaps"] = len(healing)
    return {"delete": dict(delete), "insert": insert, "healing": healing, "counts": dict(counts)}


def _load_state(session, sitemap_ids):
    art = {r[0] for r in session.execute(text("SELECT sitemap_id FROM articles WHERE sitemap_id = ANY(:i)"),
                                         {"i": list(sitemap_ids)})}
    state = {}
    for r in session.execute(text("SELECT sitemap_id, crawl_status, fetch_failures FROM sitemaps "
                                  "WHERE sitemap_id = ANY(:i)"), {"i": list(sitemap_ids)}):
        if r.sitemap_id in art:
            state[r.sitemap_id] = "article"
        elif r.crawl_status == "rejected_filter" or r.fetch_failures >= SITEMAP_MAX_FETCH_FAILURES:
            state[r.sitemap_id] = "terminal"
        else:
            state[r.sitemap_id] = "queued"
    return state


def _crawl_running(session):
    return session.execute(text(
        "SELECT count(*) FROM crawl_log WHERE status = 'started' AND task IN ('sitemap', 'full_text', 'all') "
        "AND started_at > NOW() - INTERVAL '4 hours'")).scalar()


class _NoEmbeddings:
    """FAISS.load_local needs an embeddings object; deleting never embeds."""
    def embed_documents(self, texts):
        raise RuntimeError("repair must not embed")

    def embed_query(self, text_):
        raise RuntimeError("repair must not embed")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write the repair (default: dry run)")
    args = ap.parse_args(argv)

    from langchain_community.vectorstores import FAISS
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    stores = {db: FAISS.load_local(db, _NoEmbeddings(), allow_dangerous_deserialization=True)
              for db in (VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2)}
    index_docs = {db: docs_by_key(vs.docstore._dict) for db, vs in stores.items()}
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        chunk_rows = {(r.sitemap_id, r.chunk_level, r.chunk_index): r.embedding_id for r in session.execute(text(
            "SELECT sitemap_id, chunk_level, chunk_index, embedding_id FROM chunks"))}
        all_sids = {k[0] for by_key in index_docs.values() for k in by_key} | {k[0] for k in chunk_rows}
        state = _load_state(session, all_sids)
        running = _crawl_running(session)
    p = plan(index_docs, state, chunk_rows)
    for k, v in sorted(p["counts"].items()):
        logger.info("  %-28s %8d", k, v)
    for db, ids in p["delete"].items():
        logger.info("  %s: %d vector(s) to delete", db, len(ids))
    if not args.apply:
        logger.info("[dry-run] nothing written. `--apply` to repair.")
        return 0
    if running:
        logger.error("%d crawl(s) still 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl", running)
        return 2
    if not p["delete"] and not p["insert"] and not p["delete_chunk_sitemaps"]:
        logger.info("Nothing to repair.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, "faiss_%s" % stamp)
    for db in stores:
        shutil.copytree(db, os.path.join(backup, os.path.basename(db.rstrip("/\\"))))
    logger.info("FAISS copied to %s", backup)

    for db, ids in p["delete"].items():
        if ids:
            stores[db].delete(ids)
            ChunkFAISSDatasource._atomic_save_local(stores[db], db)
            logger.info("%s: deleted %d vector(s), saved", db, len(ids))

    doomed = sorted(p["delete_chunk_sitemaps"])
    if doomed:
        import json
        with client.get_session() as session:
            rows = [dict(r._mapping) for r in session.execute(text(
                "SELECT chunk_id, sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, is_last_chunk, "
                "text_content, token_count, embedding_id, chunk_status FROM chunks WHERE sitemap_id = ANY(:i)"),
                {"i": doomed})]
        path = os.path.join(backup, "orphan_chunk_rows.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, default=str)
        with client.get_session() as session:
            n = session.execute(text(
                "DELETE FROM chunks c WHERE c.sitemap_id = ANY(:i) "
                "AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = c.sitemap_id)"),
                {"i": doomed}).rowcount
            session.commit()
        logger.info("deleted %d orphan chunk row(s) of %d terminal sitemap(s); backup %s", n, len(doomed), path)

    if p["insert"]:
        totals = collections.Counter((db, k[0], k[1]) for db, by_key in index_docs.items() for k in by_key)
        rows = []
        for db, key, doc_id in p["insert"]:
            doc = stores[db].docstore._dict[doc_id]
            n = totals[(db, key[0], key[1])]
            rows.append({"sid": key[0], "lvl": key[1], "idx": key[2], "total": n,
                         "first": key[2] == 0, "last": key[2] == n - 1, "text": doc.page_content,
                         "tok": len(doc.page_content.split()), "eid": doc_id})
        with client.get_session() as session:
            for r in rows:
                session.execute(text(
                    "INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                    "is_last_chunk, text_content, token_count, embedding_id, chunk_status, created_at) "
                    "VALUES (:sid, :lvl, :idx, :total, :first, :last, :text, :tok, :eid, 'embedded', NOW()) "
                    "ON CONFLICT (sitemap_id, chunk_level, chunk_index) DO NOTHING"), r)
            session.commit()
        logger.info("inserted %d chunk row(s) from the docstore", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
