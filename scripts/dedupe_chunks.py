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
    python scripts/dedupe_chunks.py [--dry-run] [--allow-divergent]

DBT-21 (#72):
  * The JSON backup written to backups/ before any delete holds every `chunks`
    column of every deleted row (text_content included), so a row can be
    re-inserted from it alone.
  * A group whose members' text_content differs is two extractions of one
    article, not a copy: deleting a loser loses text. --dry-run reports how
    many such groups there are, and the real run refuses them unless
    --allow-divergent is given.
  * Vectors are deleted before rows, and only the ids still in each docstore.
    A run killed between the phases (or one whose L2 delete raised after L1
    was saved) leaves the duplicate rows in place, so re-running recomputes
    the same losers and finishes the job: the end state is the same. The
    reverse order would leave stray vectors that no re-run can find, because
    the rows that point at them would be gone.
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
    SELECT c.*,
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


# Not stored data: `referenced` is computed by the SELECT, `fts_vector` is a
# GENERATED column that Postgres refuses in an INSERT and rebuilds by itself.
_NOT_BACKED_UP = frozenset({"referenced", "fts_vector"})


def _backup_entry(row) -> dict:
    """Every stored chunks column of `row` (DBT-21): the entry can be
    INSERTed back as it is."""
    return {k: v for k, v in row._mapping.items() if k not in _NOT_BACKED_UP}


def _divergent_groups(groups) -> list:
    """Keys of the groups whose members do not all carry the same text."""
    return [key for key, rows in groups.items() if len({r.text_content for r in rows}) > 1]


def _delete_present(vs, ids, path, faiss_datasource) -> int:
    """Delete from `vs` the `ids` it still holds and save it. Ids already gone
    (an earlier, interrupted run) are skipped: FAISS.delete raises on them."""
    present = [i for i in ids if i in vs.docstore._dict]
    if present:
        vs.delete(present)
        faiss_datasource._atomic_save_local(vs, path)  # DBT-10: crash-safe swap
    return len(present)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, change nothing")
    parser.add_argument("--allow-divergent", action="store_true",
                        help="Also delete losers whose text differs from their keeper's (the backup keeps it)")
    args = parser.parse_args()
    # OPS-26 (#175): not while a scheduled crawl holds FAISS in memory.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if not args.dry_run and refused_by_run_lock(logger):
        return 2

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

    divergent = _divergent_groups(groups)
    if divergent:
        logger.warning("%d group(s) have members with DIFFERENT text_content (two extractions, not copies): %s",
                       len(divergent), divergent[:20])

    if args.dry_run:
        by_level = defaultdict(int)
        for r in losers:
            by_level[r.chunk_level] += 1
        logger.info("[dry-run] Would delete: %s", dict(by_level))
        return 0

    if divergent and not args.allow_divergent:
        logger.error("Refusing: %d group(s) would lose text that exists nowhere else. Read them, then re-run "
                     "with --allow-divergent (the backup keeps every deleted row).", len(divergent))
        return 1

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"dbt09_dedupe_chunks_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([_backup_entry(r) for r in losers], f, default=str, indent=2)
    logger.info("Backed up %d row(s) to %s", len(losers), backup_path)

    faiss_datasource = ChunkFAISSDatasource()
    l1_ids = [r.embedding_id for r in losers if r.chunk_level == 1 and r.embedding_id]
    l2_ids = [r.embedding_id for r in losers if r.chunk_level == 2 and r.embedding_id]
    for vs, ids, path in ((faiss_datasource.vs_l1, l1_ids, VECTOR_DB_NAME_L1),
                          (faiss_datasource.vs_l2, l2_ids, VECTOR_DB_NAME_L2)):
        if ids:
            n = _delete_present(vs, ids, path, faiss_datasource)
            logger.info("Deleted %d vector(s) from %s (%d already gone)", n, path, len(ids) - n)

    with client.get_session() as session:
        session.execute(_DELETE_SQL, {"ids": [r.chunk_id for r in losers]})
        session.commit()
    logger.info("Deleted %d duplicate chunks row(s).", len(losers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
