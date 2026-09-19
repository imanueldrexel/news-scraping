#!/usr/bin/env python3
"""
DBT-09: delete the losing row of every duplicate `chunks` group (same
sitemap_id, chunk_level, chunk_index, different chunk_id and embedding_id) so
scripts/migrate_chunks_unique.sql's unique index can be created afterward.
Also removes the loser's now-orphaned vector from the matching FAISS index
(L1 or L2 by chunk_level) via FAISS.delete(), instead of leaving stray
duplicate vectors for "the next rebuild" -- LangChain's FAISS.delete() is a
real, supported op (verified against the installed langchain_community).

Per group: keep the row entity_mentions.chunk_id references, if any (its hard
FK would break otherwise); else keep the lowest chunk_id (the ticket's own
proposed rule). If a group has *two* entity_mentions-referenced rows, this is
an unresolvable conflict -- abort rather than guess, same posture as
migrate_articles_unique_sitemap.sql (DBT-07) took for `articles`.

Usage:
    python scripts/dedupe_chunks.py [--dry-run]

A JSON backup of every deleted row is written to backups/ before any delete.
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

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

_DUP_GROUPS_SQL = text("""
    SELECT c.chunk_id, c.sitemap_id, c.chunk_level, c.chunk_index, c.embedding_id,
           EXISTS (SELECT 1 FROM entity_mentions em WHERE em.chunk_id = c.chunk_id) AS referenced
    FROM chunks c
    WHERE (c.sitemap_id, c.chunk_level, c.chunk_index) IN (
        SELECT sitemap_id, chunk_level, chunk_index FROM chunks GROUP BY 1, 2, 3 HAVING COUNT(*) > 1
    )
    ORDER BY c.sitemap_id, c.chunk_level, c.chunk_index, c.chunk_id
""")

_DELETE_SQL = text("DELETE FROM chunks WHERE chunk_id = ANY(:ids)")


def _pick_loser_ids(rows):
    """rows: chunk_id, sitemap_id, chunk_level, chunk_index, embedding_id, referenced
    for one duplicate group. Returns (loser_rows, conflict) -- conflict is True if
    more than one row is entity_mentions-referenced (unresolvable without a human)."""
    referenced = [r for r in rows if r.referenced]
    if len(referenced) > 1:
        return [], True
    if len(referenced) == 1:
        keeper_id = referenced[0].chunk_id
    else:
        keeper_id = min(r.chunk_id for r in rows)
    return [r for r in rows if r.chunk_id != keeper_id], False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, change nothing")
    args = parser.parse_args()

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(_DUP_GROUPS_SQL).fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[(r.sitemap_id, r.chunk_level, r.chunk_index)].append(r)

    losers = []
    conflicts = []
    for key, group_rows in groups.items():
        group_losers, conflict = _pick_loser_ids(group_rows)
        if conflict:
            conflicts.append(key)
        else:
            losers.extend(group_losers)

    logger.info("%d duplicate group(s), %d row(s) to delete, %d unresolvable conflict(s)",
                len(groups), len(losers), len(conflicts))
    if conflicts:
        logger.error("Conflicting groups (2+ entity_mentions-referenced rows, resolve manually): %s", conflicts)
        return 1

    if not losers:
        logger.info("Nothing to do.")
        return 0

    if args.dry_run:
        by_level = defaultdict(int)
        for r in losers:
            by_level[r.chunk_level] += 1
        logger.info("[dry-run] Would delete: %s", dict(by_level))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"dbt09_dedupe_chunks_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([dict(r._mapping) for r in losers], f, default=str, indent=2)
    logger.info("Backed up %d row(s) to %s", len(losers), backup_path)

    faiss_datasource = ChunkFAISSDatasource()
    l1_ids = [r.embedding_id for r in losers if r.chunk_level == 1 and r.embedding_id]
    l2_ids = [r.embedding_id for r in losers if r.chunk_level == 2 and r.embedding_id]
    if l1_ids:
        faiss_datasource.vs_l1.delete(l1_ids)
        faiss_datasource._atomic_save_local(faiss_datasource.vs_l1, VECTOR_DB_NAME_L1)  # DBT-10: crash-safe swap
        logger.info("Deleted %d vector(s) from %s", len(l1_ids), VECTOR_DB_NAME_L1)
    if l2_ids:
        faiss_datasource.vs_l2.delete(l2_ids)
        faiss_datasource._atomic_save_local(faiss_datasource.vs_l2, VECTOR_DB_NAME_L2)  # DBT-10: crash-safe swap
        logger.info("Deleted %d vector(s) from %s", len(l2_ids), VECTOR_DB_NAME_L2)

    with client.get_session() as session:
        session.execute(_DELETE_SQL, {"ids": [r.chunk_id for r in losers]})
        session.commit()
    logger.info("Deleted %d duplicate chunks row(s).", len(losers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
