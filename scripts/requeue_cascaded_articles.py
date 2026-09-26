#!/usr/bin/env python3
"""
SRC-54 (#177): re-queue articles whose stored body repeats itself, so the fixed
extractor fetches them again through the real pipeline.

EMITENNEWS leaves <p> unclosed. html.parser nested every paragraph inside the one
before it, so each stored paragraph held the rest of the article too, and all 935
EMITENNEWS articles saved on 2026-09-26 carry a body 3-5x its real length. The
copies went into three stores: `articles.extracted_text`, the `chunks` rows, and
their NEWS_L1/NEWS_L2 vectors.

This script does not re-extract text itself. It removes a cascaded article from
all three stores together and puts its sitemap back in the queue. The next
`full_text` then fetches the page, extracts it with the fixed extractor, runs the
filter, chunks, embeds and saves it exactly like any new article. Re-implementing
that path here would mean a second copy of the pipeline to keep in sync.

Per sitemap, in this order:
  1. its vectors are deleted from NEWS_L1/NEWS_L2 (atomic save). They must go:
     SYS-17's reuse path finds an existing vector by (sitemap, level, index) and
     would link the new chunk rows to the old cascaded vectors.
  2. its `chunks` rows, then its `articles` row, are deleted (chunks reference
     articles). `entity_mentions` must be empty for it; the script refuses
     otherwise, because extracted entities would be lost.
  3. the sitemap is reset to `crawl_status = 'pending'`, `last_crawl_attempt =
     NULL`, so `load_all_sitemaps` offers it on the next run.

Selection is by content, not by source: an article qualifies only when
`core.utils.utils.is_cascaded` says its stored paragraphs cascade.

Dry run by default. `--apply` first copies NEWS_L1/NEWS_L2 and writes the rows it
deletes to backups/src54_<stamp>/. It refuses while a scheduled crawl holds the
run lock (OPS-26) or a crawl_log row is `started` in the last 4 h.

    python scripts/requeue_cascaded_articles.py --website EMITENNEWS           # dry run
    python scripts/requeue_cascaded_articles.py --website EMITENNEWS --apply
"""
import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2  # noqa: E402
from newscrawler.core.utils.utils import is_cascaded  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")


def select_cascaded(rows):
    """Pure. `rows`: (sitemap_id, extracted_text) pairs. The sitemap_ids whose
    stored body cascades. Stored bodies are paragraphs joined by a blank line
    (SYS-18)."""
    return sorted(sid for sid, body in rows if is_cascaded((body or "").split("\n\n")))


def vector_ids_for(docstore_dict, sitemap_ids):
    """Pure. Docstore ids of every vector belonging to one of `sitemap_ids`."""
    wanted = set(sitemap_ids)
    return [doc_id for doc_id, doc in docstore_dict.items()
            if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in wanted]


def _crawl_running(session):
    return session.execute(text(
        "SELECT count(*) FROM crawl_log WHERE status = 'started' AND task IN ('sitemap', 'full_text', 'all') "
        "AND started_at > NOW() - INTERVAL '4 hours'")).scalar()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", required=True, help="Source to scan, e.g. EMITENNEWS")
    ap.add_argument("--apply", action="store_true", help="Write (default: dry run)")
    args = ap.parse_args(argv)
    website = args.website.strip().upper()

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    from newscrawler.tools.run_lock import RunLockHeld, refuse_if_running

    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(text(
            "SELECT a.sitemap_id, a.extracted_text FROM articles a JOIN sitemaps s USING (sitemap_id) "
            "WHERE s.sources = :w"), {"w": website}).fetchall()
        targets = select_cascaded((r.sitemap_id, r.extracted_text) for r in rows)
        chunk_rows = session.execute(text("SELECT count(*) FROM chunks WHERE sitemap_id = ANY(:i)"),
                                     {"i": targets}).scalar() if targets else 0
        mentions = session.execute(text("SELECT count(*) FROM entity_mentions WHERE sitemap_id = ANY(:i)"),
                                   {"i": targets}).scalar() if targets else 0
        running = _crawl_running(session)

    logger.info("%s: %d article(s), %d cascaded; %d chunk row(s), %d entity mention(s) on them",
                website, len(rows), len(targets), chunk_rows, mentions)
    if not targets:
        logger.info("Nothing to re-queue.")
        return 0

    from langchain_community.vectorstores import FAISS
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from repair_store_consistency import _NoEmbeddings

    stores = {db: FAISS.load_local(db, _NoEmbeddings(), allow_dangerous_deserialization=True)
              for db in (VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2)}
    doomed_vectors = {db: vector_ids_for(vs.docstore._dict, targets) for db, vs in stores.items()}
    for db, ids in doomed_vectors.items():
        logger.info("  %s: %d vector(s) to delete", db, len(ids))

    if not args.apply:
        logger.info("[dry-run] nothing written. `--apply` to delete these from all three stores and re-queue.")
        return 0
    if mentions:
        logger.error("%d entity mention(s) would be lost; this script only handles unextracted articles", mentions)
        return 2
    try:
        refuse_if_running()
    except RunLockHeld as e:
        logger.error("%s", e)
        return 2
    if running:
        logger.error("%d crawl(s) still 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl",
                     running)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, "src54_%s" % stamp)
    for db in stores:
        shutil.copytree(db, os.path.join(backup, os.path.basename(db.rstrip("/\\"))))
    with client.get_session() as session:
        dump = {
            "articles": [dict(r._mapping) for r in session.execute(text(
                "SELECT * FROM articles WHERE sitemap_id = ANY(:i)"), {"i": targets})],
            "chunks": [dict(r._mapping) for r in session.execute(text(
                "SELECT chunk_id, sitemap_id, article_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                "is_last_chunk, text_content, token_count, embedding_id, chunk_status FROM chunks "
                "WHERE sitemap_id = ANY(:i)"), {"i": targets})],
            "sitemaps": [dict(r._mapping) for r in session.execute(text(
                "SELECT sitemap_id, crawl_status, last_crawl_attempt, fetch_failures FROM sitemaps "
                "WHERE sitemap_id = ANY(:i)"), {"i": targets})],
        }
    with open(os.path.join(backup, "rows.json"), "w", encoding="utf-8") as f:
        json.dump(dump, f, default=str)
    logger.info("backup: %s (FAISS + %d article, %d chunk rows)", backup, len(dump["articles"]), len(dump["chunks"]))

    # Vectors first: a failure after this point leaves articles without vectors,
    # which check_store_consistency reports and the requeue below would heal; the
    # other order would leave vectors the reuse path links to on the next crawl.
    for db, ids in doomed_vectors.items():
        if ids:
            stores[db].delete(ids)
            ChunkFAISSDatasource._atomic_save_local(stores[db], db)
            logger.info("%s: deleted %d vector(s), saved", db, len(ids))

    with client.get_session() as session:
        n_chunks = session.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:i)"), {"i": targets}).rowcount
        n_articles = session.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:i)"),
                                     {"i": targets}).rowcount
        n_requeued = session.execute(text(
            "UPDATE sitemaps SET crawl_status = 'pending', last_crawl_attempt = NULL WHERE sitemap_id = ANY(:i)"),
            {"i": targets}).rowcount
        session.commit()
    logger.info("deleted %d chunk row(s) and %d article(s); re-queued %d sitemap(s)",
                n_chunks, n_articles, n_requeued)
    return 0


if __name__ == "__main__":
    sys.exit(main())
