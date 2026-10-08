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
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_FETCH_SQL = text("""
    SELECT a.sitemap_id, a.extracted_text, a.writer,
           s.headline, s.sources, s.category, s.posted_at
    FROM articles a
    JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
    WHERE (
        NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 1)
        OR NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id AND c.chunk_level = 2)
      )
      AND (:website IS NULL OR s.sources = :website)
    ORDER BY a.sitemap_id
""")


def rechunk_articles(repo, chunker, rows, group_size=1):
    """Re-chunk and save `rows` (articles with an `articles` row but missing chunks) from
    their stored text. Returns (repaired, empty, failed). Used by this script and by
    scripts/repair_boilerplate_bodies.py (SYS-73), which wraps it in `deferred_embeddings`
    so a block of articles costs one FAISS save instead of one per article.

    `group_size`: articles per `save_chunk_data` call, so their chunks are embedded in one batch
    (SYS-109: the whole corpus at ~8 windows an article). A group that fails is saved again
    article by article, so one bad article fails alone."""
    repaired, empty, failed = 0, 0, 0
    group = []

    def save_group():
        nonlocal repaired, failed
        if not group:
            return
        try:
            repo.save_chunk_data([c for _, chunks in group for c in chunks])
            repaired += len(group)
        except Exception as e:
            if len(group) == 1:
                logger.error("sitemap_id %d: failed to save chunks: %s", group[0][0], e)
                failed += 1
            else:
                logger.warning("a group of %d articles failed to save (%s); saving them one by one", len(group), e)
                for sitemap_id, chunks in group:
                    try:
                        repo.save_chunk_data(chunks)
                        repaired += 1
                    except Exception as e1:
                        logger.error("sitemap_id %d: failed to save chunks: %s", sitemap_id, e1)
                        failed += 1
        group.clear()

    for row in rows:
        # SYS-18: extracted_text is prose joined with "\n\n" at the write boundary
        # (sql_alchemy_articles_data_source.save_newsdetails); split it the same way.
        paragraphs = [p for p in (row.extracted_text or "").split("\n\n") if p.strip()]
        if not paragraphs:
            logger.warning("sitemap_id %d: extracted_text is empty, skipping", row.sitemap_id)
            empty += 1
            continue

        if not row.posted_at:
            logger.warning("sitemap_id %d: no posted_at, skipping", row.sitemap_id)
            empty += 1
            continue
        posted_at_dt = datetime.strptime(str(row.posted_at), "%Y%m%d")

        news = NewsDetailsDTO(
            sitemap_id=row.sitemap_id,
            extracted_text=paragraphs,
            reporter=row.writer,
            meta_data={"title": row.headline, "posted_at": row.posted_at},
        )
        sitemap = SitemapDTO(
            headline=row.headline, link="", sources=row.sources, category=row.category,
            timestamp=posted_at_dt, sitemap_id=row.sitemap_id,
        )
        chunks = chunker.chunk(news, sitemap)
        if not chunks:
            logger.warning("sitemap_id %d: chunker produced 0 chunks, skipping", row.sitemap_id)
            empty += 1
            continue

        group.append((row.sitemap_id, chunks))
        if len(group) >= group_size:
            save_group()
    save_group()
    return repaired, empty, failed


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
