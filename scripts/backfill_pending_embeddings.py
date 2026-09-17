#!/usr/bin/env python3
"""
DBT-17: repair `chunks` rows stuck at chunk_status='pending_embedding' with
embedding_id IS NULL -- rows that exist in Postgres but were never embedded
into FAISS. Unlike backfill_orphan_chunks.py (SYS-17/SYS-25's fix, which
re-chunks from articles.extracted_text for rows *missing* at a level), these
rows already hold their own text_content, so this only needs to embed that
text and UPDATE the existing row in place -- no re-chunk, no re-crawl.

Historical note (DBT-17, #58): the 142 rows this was written for are dated
2026-06-01, one day before the SYS-17 WARTAEKONOMI incident, and predate
every fix to the embed path (SYS-17 103980b, SYS-25 7cba3bf) as well as the
original write path (9b08107). None of that code, at any point in its
history, could have inserted an embedding_id=NULL row: the original
save_chunk_data dropped unembedded chunks rather than inserting them with
NULL, and the current one always embeds before inserting. These rows were
most likely written by a one-off manual/REPL action during that day's
backfill work, not a reproducible pipeline bug -- this script repairs the
data; it is not a guard against a recurrence current code cannot cause.

Usage:
    python scripts/backfill_pending_embeddings.py [--website NAME] [--dry-run]

A JSON backup of every row touched is written to backups/ before the UPDATE.
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

from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

_FETCH_SQL = text("""
    SELECT c.chunk_id, c.sitemap_id, c.chunk_level, c.chunk_index, c.chunk_total,
           c.is_first_chunk, c.is_last_chunk, c.text_content, c.token_count,
           s.headline, s.sources, s.category, s.posted_at
    FROM chunks c
    JOIN sitemaps s ON s.sitemap_id = c.sitemap_id
    WHERE c.embedding_id IS NULL
      AND (:website IS NULL OR s.sources = :website)
    ORDER BY c.chunk_id
""")

_UPDATE_SQL = text("""
    UPDATE chunks SET embedding_id = :embedding_id, chunk_status = :chunk_status
    WHERE chunk_id = :chunk_id
""")


def _row_to_dto(row) -> ChunkDTO:
    return ChunkDTO(
        sitemap_id=row.sitemap_id,
        chunk_level=row.chunk_level,
        chunk_index=row.chunk_index,
        chunk_total=row.chunk_total,
        is_first_chunk=row.is_first_chunk,
        is_last_chunk=row.is_last_chunk,
        text_content=row.text_content,
        token_count=row.token_count,
        title=row.headline,
        source=row.sources,
        category=row.category,
        posted_at=row.posted_at,
        chunk_id=row.chunk_id,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Limit to one source (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    args = parser.parse_args()

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(_FETCH_SQL, {"website": args.website}).fetchall()

    logger.info("%d pending-embedding chunk row(s) found%s", len(rows), f" for {args.website}" if args.website else "")
    if not rows:
        return

    if args.dry_run:
        by_source = {}
        for r in rows:
            by_source[r.sources] = by_source.get(r.sources, 0) + 1
        logger.info("[dry-run] Would embed and update: %s", by_source)
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"dbt17_pending_embeddings_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([dict(r._mapping) for r in rows], f, default=str, indent=2)
    logger.info("Backed up %d row(s) to %s", len(rows), backup_path)

    chunks = [_row_to_dto(r) for r in rows]
    faiss_datasource = ChunkFAISSDatasource()
    embedded = faiss_datasource.save(chunks)

    updated = [c for c in embedded if c.embedding_id]
    skipped = len(embedded) - len(updated)
    if skipped:
        logger.warning("%d chunk(s) came back without an embedding_id -- not updated", skipped)

    with client.get_session() as session:
        session.execute(_UPDATE_SQL, [
            {"embedding_id": c.embedding_id, "chunk_status": c.chunk_status, "chunk_id": c.chunk_id}
            for c in updated
        ])
        session.commit()

    logger.info("Done. updated=%d skipped=%d (of %d)", len(updated), skipped, len(rows))


if __name__ == "__main__":
    main()
