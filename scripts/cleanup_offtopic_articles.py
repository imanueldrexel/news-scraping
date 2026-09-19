#!/usr/bin/env python3
"""
SYS-31: delete the articles/chunks/FAISS vectors for rows that were saved
before the category deny-list existed (fixed 2026-09-19) and are off-topic by
the same `is_offtopic_category()` the live filter now uses -- imported
directly from `newscrawler.core.importance_filter`, never re-derived, so this
script can't drift from what the pipeline actually rejects today.

Any sitemap_id already referenced by `entity_mentions` (Gemini already
extracted entities from it) is skipped, not deleted -- `entity_mentions` has
hard FKs to `sitemaps`/`articles`/`chunks` with no `ON DELETE CASCADE`, so
deleting underneath it would violate a constraint; same "referenced ->
keeper" posture as dedupe_chunks.py/dedupe_sitemap_links.py.

`sitemaps` rows are NOT deleted (unlike the dedupe scripts) -- only
`articles` and `chunks`. The sitemap's `crawl_status` is set to
'rejected_filter' (SYS-16's terminal state) so `load_all_sitemaps` never
re-offers it; re-crawling would just hit the same category deny-list again
anyway, no reason to waste a fetch on a known answer.

Ordering (DBT-21's pattern, applied in dedupe_sitemap_links.py): a JSON
backup of every `articles`/`chunks` row about to be deleted is written to
backups/ first; then the SQL changes (chunks delete, articles delete,
sitemaps status update) commit in ONE transaction; then FAISS vectors are
removed by scanning both docstores for metadata.sitemap_id in the target set
(not chunks.embedding_id, so a vector whose chunks row is already gone is
still found). If the FAISS step fails after the SQL commit, resume it alone:

    python scripts/cleanup_offtopic_articles.py --faiss-only 12345,67890

Usage:
    python scripts/cleanup_offtopic_articles.py --dry-run
    python scripts/cleanup_offtopic_articles.py
    python scripts/cleanup_offtopic_articles.py --faiss-only <sitemap_id,...>
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.importance_filter import is_offtopic_category
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

_CANDIDATES_SQL = text("""
    SELECT a.sitemap_id, s.category, s.sources,
           EXISTS (SELECT 1 FROM entity_mentions em WHERE em.sitemap_id = a.sitemap_id) AS referenced
    FROM articles a JOIN sitemaps s USING (sitemap_id)
""")

_BACKUP_SQL = {
    "articles": text("SELECT * FROM articles WHERE sitemap_id = ANY(:ids)"),
    "chunks":   text("SELECT * FROM chunks   WHERE sitemap_id = ANY(:ids)"),
}

_DELETE_CHUNKS_SQL = text("DELETE FROM chunks WHERE sitemap_id = ANY(:ids)")
_DELETE_ARTICLES_SQL = text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)")
_MARK_REJECTED_SQL = text("UPDATE sitemaps SET crawl_status = 'rejected_filter' WHERE sitemap_id = ANY(:ids)")


def find_offtopic_sitemap_ids(session):
    """Returns (targets, skipped_referenced, by_category). targets: every
    sitemap_id whose category is_offtopic_category() rejects and which has no
    entity_mentions row. skipped_referenced: same but excluded for having one.
    by_category: {(source, category): count} over targets only."""
    rows = session.execute(_CANDIDATES_SQL).fetchall()
    targets, skipped = [], []
    by_category = {}
    for r in rows:
        if not is_offtopic_category(r.category):
            continue
        if r.referenced:
            skipped.append(r.sitemap_id)
            continue
        targets.append(r.sitemap_id)
        key = (r.sources, r.category)
        by_category[key] = by_category.get(key, 0) + 1
    return targets, skipped, by_category


def _faiss_ids_for_sitemaps(vs, sitemap_ids) -> list:
    """Docstore keys of every vector in `vs` whose metadata.sitemap_id is in sitemap_ids."""
    wanted = {int(s) for s in sitemap_ids}
    return [
        doc_id for doc_id, doc in vs.docstore._dict.items()
        if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in wanted
    ]


def delete_faiss_vectors(target_ids) -> dict:
    """Remove every L1/L2 vector belonging to target_ids. Returns
    {index_name: deleted_count}. Loads the embedding model (~10 s)."""
    from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource,
    )

    ds = ChunkFAISSDatasource()
    deleted = {}
    for name, vs in ((VECTOR_DB_NAME_L1, ds.vs_l1), (VECTOR_DB_NAME_L2, ds.vs_l2)):
        ids = _faiss_ids_for_sitemaps(vs, target_ids)
        if ids:
            vs.delete(ids)
            ds._atomic_save_local(vs, name)  # DBT-10: crash-safe swap, not a direct in-place overwrite
        deleted[name] = len(ids)
        logger.info("%s: deleted %d vector(s) for %d sitemap_id(s)", name, len(ids), len(target_ids))
    return deleted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, change nothing")
    parser.add_argument("--faiss-only", help="Comma-separated sitemap_ids: resume only the FAISS-vector step")
    args = parser.parse_args(argv)

    if args.faiss_only:
        ids = [int(x) for x in args.faiss_only.split(",") if x.strip()]
        deleted = delete_faiss_vectors(ids)
        logger.info("FAISS-only resume complete: %s", deleted)
        return 0

    client = SQLAlchemyClient()
    with client.get_session() as session:
        targets, skipped, by_category = find_offtopic_sitemap_ids(session)

    logger.info("%d off-topic article(s) to delete, %d skipped (entity_mentions-referenced)",
                len(targets), len(skipped))
    for (source, category), count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        logger.info("  %-16s %-24s %d", source, category, count)

    if not targets:
        logger.info("Nothing to do.")
        return 0

    if args.dry_run:
        logger.info("[dry-run] Would delete %d articles row(s), their chunks, and FAISS vectors; "
                     "mark their sitemaps rejected_filter.", len(targets))
        if skipped:
            logger.info("[dry-run] %d skipped as entity_mentions-referenced: %s",
                         len(skipped), skipped[:20])
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"sys31_cleanup_offtopic_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with client.get_session() as session:
        backup = {name: [dict(r._mapping) for r in session.execute(sql, {"ids": targets}).fetchall()]
                   for name, sql in _BACKUP_SQL.items()}
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, default=str, indent=2)
    logger.info("Backed up %d articles row(s), %d chunks row(s) to %s",
                len(backup["articles"]), len(backup["chunks"]), backup_path)

    with client.get_session() as session:
        session.execute(_DELETE_CHUNKS_SQL, {"ids": targets})
        session.execute(_DELETE_ARTICLES_SQL, {"ids": targets})
        session.execute(_MARK_REJECTED_SQL, {"ids": targets})
        session.commit()
    logger.info("Deleted %d articles row(s) and their chunks; marked sitemaps rejected_filter.", len(targets))

    deleted = delete_faiss_vectors(targets)
    logger.info("Done. FAISS vectors deleted: %s", deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
