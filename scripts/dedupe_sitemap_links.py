#!/usr/bin/env python3
"""
SYS-29: collapse every `sitemaps` link that has more than one row down to one, so
scripts/migrate_sitemaps_unique_link.sql's unique index can be created afterward.

save_sitemaps used to dedup on (link, posted_at); a URL that a site re-listed with
a different news:publication_date, or whose posted_at derivation changed (SYS-11),
got a second row, then a second articles row, then duplicate chunks rows and
FAISS vectors. Production on 2026-09-18 held 2 such links: a SINDONEWS pair with a
full articles/chunks/FAISS copy on BOTH sides, and a VIVA pair with nothing
attached to either.

Per link group the keeper is, in order: the row entity_mentions.sitemap_id
references (hard FK; two referenced rows in one group is an unresolvable conflict
-- abort, same posture as DBT-07/DBT-09); else the row that has an articles row
(knowledge_extracted=1 first, so Gemini is not re-paid); else the row that has
chunks rows; else the lowest sitemap_id. Only losers are ever deleted, together
with their own articles/chunks rows and FAISS vectors.

Ordering (DBT-21's critique of dedupe_chunks.py applied): a JSON backup of every
row about to be deleted (full sitemaps/articles/chunks rows, not just keys) is
written to backups/ first; then all SQL deletes commit in ONE transaction; then
the losers' FAISS vectors are removed. If the FAISS step fails after the SQL
commit, the vectors are orphans (check_store_consistency.py's faiss_no_chunks
class) and this script resumes that half alone:

    python scripts/dedupe_sitemap_links.py --faiss-only 85673,86871

FAISS vectors are located by scanning each docstore for metadata.sitemap_id in
the loser set, not by chunks.embedding_id, so a vector whose chunks row is
missing or has embedding_id NULL (DBT-23) is still found.

Usage:
    python scripts/dedupe_sitemap_links.py --dry-run
    python scripts/dedupe_sitemap_links.py
    python scripts/dedupe_sitemap_links.py --faiss-only <sitemap_id,...>
"""
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# One row per sitemaps row that shares its link with at least one other row, with
# the evidence the keeper rule needs. Ordered so the first row of each group is
# the keeper.
_DUP_GROUPS_SQL = text("""
    SELECT s.sitemap_id, s.link, s.sources, s.posted_at, s.crawl_status,
           (EXISTS (SELECT 1 FROM entity_mentions em WHERE em.sitemap_id = s.sitemap_id)
            OR EXISTS (SELECT 1 FROM entity_mentions em JOIN articles a ON a.articles_id = em.article_id
                       WHERE a.sitemap_id = s.sitemap_id))                              AS referenced,
           EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id)          AS has_article,
           COALESCE((SELECT MAX(a.knowledge_extracted) FROM articles a WHERE a.sitemap_id = s.sitemap_id), 0) AS knowledge_extracted,
           (SELECT COUNT(*) FROM chunks c WHERE c.sitemap_id = s.sitemap_id)            AS chunk_count
    FROM sitemaps s
    WHERE s.link IN (SELECT link FROM sitemaps GROUP BY link HAVING COUNT(*) > 1)
    ORDER BY s.link, referenced DESC, has_article DESC, knowledge_extracted DESC, chunk_count DESC, s.sitemap_id ASC
""")

_BACKUP_SQL = {
    "sitemaps": text("SELECT * FROM sitemaps WHERE sitemap_id = ANY(:ids)"),
    "articles": text("SELECT * FROM articles WHERE sitemap_id = ANY(:ids)"),
    "chunks":   text("SELECT * FROM chunks   WHERE sitemap_id = ANY(:ids)"),
}

# FK order: chunks and articles reference sitemaps. entity_mentions is never
# touched -- the keeper rule guarantees a loser has none.
_DELETE_SQL = [
    text("DELETE FROM chunks   WHERE sitemap_id = ANY(:ids)"),
    text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)"),
    text("DELETE FROM sitemaps WHERE sitemap_id = ANY(:ids)"),
]


def pick_losers(group_rows):
    """group_rows: the rows for ONE link, already in keeper-first order (see
    _DUP_GROUPS_SQL). Returns (keeper, losers, conflict) -- conflict is True when
    more than one row is entity_mentions-referenced, which no rule can resolve."""
    referenced = [r for r in group_rows if r.referenced]
    if len(referenced) > 1:
        return None, [], True
    keeper = group_rows[0]
    return keeper, [r for r in group_rows[1:]], False


def _faiss_ids_for_sitemaps(vs, sitemap_ids) -> list:
    """Docstore keys of every vector in `vs` whose metadata.sitemap_id is in sitemap_ids."""
    wanted = {int(s) for s in sitemap_ids}
    return [
        doc_id for doc_id, doc in vs.docstore._dict.items()
        if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in wanted
    ]


def delete_faiss_vectors(loser_ids) -> dict:
    """Remove every L1/L2 vector belonging to the loser sitemap_ids. Returns
    {index_name: deleted_count}. Loads the embedding model (~10 s)."""
    from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource,
    )

    ds = ChunkFAISSDatasource()
    deleted = {}
    for name, vs in ((VECTOR_DB_NAME_L1, ds.vs_l1), (VECTOR_DB_NAME_L2, ds.vs_l2)):
        ids = _faiss_ids_for_sitemaps(vs, loser_ids)
        if ids:
            vs.delete(ids)
            ChunkFAISSDatasource._atomic_save_local(vs, name)  # DBT-10: crash-safe swap, not a direct in-place overwrite
        deleted[name] = len(ids)
        logger.info("%s: deleted %d vector(s) for sitemap_ids %s", name, len(ids), sorted(loser_ids))
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, change nothing")
    parser.add_argument("--faiss-only", metavar="IDS",
                        help="Resume: only remove FAISS vectors for these comma-separated loser sitemap_ids "
                             "(use after a run whose SQL committed but whose FAISS step failed)")
    args = parser.parse_args()
    # OPS-26 (#175): not while a scheduled crawl holds FAISS in memory.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if not args.dry_run and refused_by_run_lock(logger):
        return 2

    if args.faiss_only:
        loser_ids = [int(x) for x in args.faiss_only.split(",") if x.strip()]
        delete_faiss_vectors(loser_ids)
        return 0

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(_DUP_GROUPS_SQL).fetchall()

    groups = defaultdict(list)
    for r in rows:  # already ordered keeper-first within each link
        groups[r.link].append(r)

    losers, conflicts = [], []
    for link, group_rows in groups.items():
        keeper, group_losers, conflict = pick_losers(group_rows)
        if conflict:
            conflicts.append(link)
            continue
        losers.extend(group_losers)
        logger.info(
            "%s\n    keep  %d (posted_at=%s status=%s article=%s ke=%s chunks=%d)\n    drop  %s",
            link, keeper.sitemap_id, keeper.posted_at, keeper.crawl_status, keeper.has_article,
            keeper.knowledge_extracted, keeper.chunk_count,
            ", ".join(f"{r.sitemap_id} (posted_at={r.posted_at} status={r.crawl_status} article={r.has_article} "
                      f"chunks={r.chunk_count})" for r in group_losers),
        )

    logger.info("%d duplicate link(s), %d sitemaps row(s) to delete, %d unresolvable conflict(s)",
                len(groups), len(losers), len(conflicts))
    if conflicts:
        logger.error("Conflicting links (2+ entity_mentions-referenced rows, resolve manually): %s", conflicts)
        return 1
    if not losers:
        logger.info("Nothing to do.")
        return 0

    loser_ids = [r.sitemap_id for r in losers]
    with client.get_session() as session:
        backup = {
            table: [dict(row._mapping) for row in session.execute(sql, {"ids": loser_ids}).fetchall()]
            for table, sql in _BACKUP_SQL.items()
        }
    logger.info("Dependent rows on the losers: %d articles, %d chunks",
                len(backup["articles"]), len(backup["chunks"]))

    if args.dry_run:
        logger.info("[dry-run] Would delete %d sitemaps, %d articles, %d chunks row(s) and their FAISS vectors.",
                    len(backup["sitemaps"]), len(backup["articles"]), len(backup["chunks"]))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"sys29_dedupe_sitemap_links_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, default=str, indent=2)
    logger.info("Backed up to %s", backup_path)

    with client.get_session() as session:
        for sql in _DELETE_SQL:
            session.execute(sql, {"ids": loser_ids})
        session.commit()
    logger.info("Deleted %d sitemaps, %d articles, %d chunks row(s) in one transaction.",
                len(backup["sitemaps"]), len(backup["articles"]), len(backup["chunks"]))

    try:
        deleted = delete_faiss_vectors(loser_ids)
    except Exception:
        logger.exception(
            "SQL rows are gone but the FAISS step failed -- the losers' vectors are orphans. "
            "Resume with: python scripts/dedupe_sitemap_links.py --faiss-only %s",
            ",".join(str(i) for i in loser_ids),
        )
        return 1

    expected = sum(1 for c in backup["chunks"] if c.get("embedding_id"))
    actual = sum(deleted.values())
    if actual != expected:
        logger.warning("FAISS removed %d vector(s) but the deleted chunks rows carried %d embedding_id(s) "
                       "-- the store was already inconsistent for these sitemaps (see check_store_consistency.py)",
                       actual, expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
