#!/usr/bin/env python3
"""
SYS-17/SYS-25 repair: re-chunk articles missing chunks at any expected level (L1
and/or L2) despite already having an `articles` row (and, usually, existing FAISS
vectors from a prior run whose SQL insert never landed). Re-chunks directly from
articles.extracted_text (prose since SYS-18) instead of re-crawling the network, so
the exact text originally chunked is reused and the (sitemap_id, chunk_level,
chunk_index) keys line up with whatever is already in FAISS -- the fixed
save_chunk_data (DataFlowRepositoryImpl) then recovers those exact embedding_ids
instead of creating duplicate vectors.

SYS-25: a sitemap with chunks at one level and not the other used to be invisible
to this script too -- it only selected sitemaps with *zero* chunks rows. The query
below now selects "missing L1 OR missing L2"; save_chunk_data's own
(sitemap_id, chunk_level) dedup (fixed the same day) then inserts only the level
that's actually missing, so re-chunking a partially-saved article is a no-op for
the level it already has.

This is also the only chunk backfill tool (DBT-24, #79): the older
scripts/backfill_chunks.py selected by chunks.article_id (never written by the
live pipeline, so it selected every article), chunked post-SYS-18 prose as one
paragraph, and embedded into a VECTOR_DB_DIR index nothing reads -- it was
deleted rather than rewritten into a copy of this script. Everything written
here goes through DataFlowRepositoryImpl.save_chunk_data, i.e. the same
HierarchicalChunker, the same ChunkFAISSDatasource and the same NEWS_L1/NEWS_L2
indexes search_l2() and the newsletter read.

Usage:
    python scripts/backfill_orphan_chunks.py [--website NAME] [--dry-run]
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)
# DBT-67 (ADR-015): the re-embed loop every store repair shares, and its selection.
from newscrawler.tools.store_repair import ORPHAN_ARTICLES_SQL as _FETCH_SQL, rechunk_articles  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def main(argv=None) -> dict:
    """Returns {"selected", "repaired", "empty", "failed"} so the integration test
    can drive this in-process (argv=None reads sys.argv as usual), or the exit
    status 2 when a scheduled crawl holds the run lock."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Limit to one source (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    args = parser.parse_args(argv)
    # OPS-26/DBT-43: this writes NEWS_L1/L2 (through save_chunk_data); refuse at the
    # door while a scheduled crawl holds them, before any fetch or write.
    from newscrawler.tools.run_lock import refused_by_run_lock
    if not args.dry_run and refused_by_run_lock(logger):
        return 2

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(_FETCH_SQL, {"website": args.website}).fetchall()

    summary = {"selected": len(rows), "repaired": 0, "empty": 0, "failed": 0}
    logger.info("%d orphan article(s) found%s", len(rows), f" for {args.website}" if args.website else "")
    if not rows:
        return summary

    if args.dry_run:
        by_source = {}
        for r in rows:
            by_source[r.sources] = by_source.get(r.sources, 0) + 1
        logger.info("[dry-run] Would re-chunk: %s", by_source)
        return summary

    chunker = HierarchicalChunker()
    repo = DataFlowRepositoryImpl(client)

    repaired, empty, failed = rechunk_articles(repo, chunker, rows)

    logger.info("Done. repaired=%d empty=%d failed=%d (of %d)", repaired, empty, failed, len(rows))
    summary.update(repaired=repaired, empty=empty, failed=failed)
    return summary


if __name__ == "__main__":
    sys.exit(2 if main() == 2 else 0)
