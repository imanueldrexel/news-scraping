#!/usr/bin/env python3
"""
Backfill articles for sitemaps that have no article row.

Re-crawls the article-less backlog through the (now-fixed) pipeline: important
articles are saved, the rest are stamped last_crawl_attempt so they leave the queue
(Bug B). Already-embedded-but-article-less sitemaps now save their article too (Bug A).

Each pass loads up to --batch sitemaps (newest first, not recently attempted), processes
them, and marks the extracted ones attempted -- so the window advances instead of
re-grabbing the same rows. Loops until the queue for a source is drained.

Usage:
    python scripts/backfill_missing_articles.py                 # all sources in __main__.SLOW
    python scripts/backfill_missing_articles.py --website WARTAEKONOMI
    python scripts/backfill_missing_articles.py --website WARTAEKONOMI --max-passes 20
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_missing_articles")

DEFAULT_WEBSITES = [
    "KONTAN", "SINDONEWS", "CNN", "CNBC", "TRIBUN", "ANTARANEWS", "JPNN",
    "PIKIRANRAKYAT", "VIVA", "GRIDID", "IDXCHANNEL", "KOMPAS", "KUMPARAN",
    "TIRTO", "INVESTORID", "MEDIAINDONESIA", "LIPUTAN6", "KAPANLAGI",
    "BATAMPOS", "BISNIS", "TEMPO", "SUARA", "BERITASATU", "DETIK", "MERDEKA",
    "ERAID", "OKEZONE", "INEWS", "WARTAEKONOMI", "TVONENEWS", "IDNTIMES",
    "EMITENNEWS",
]


def build_service():
    client = SQLAlchemyClient()
    repo = DataFlowRepositoryImpl(client)
    return CrawlerServiceImpl(repo, chunker=HierarchicalChunker()), repo


def drain_website(service, repo, website, max_passes):
    for attempt in range(1, max_passes + 1):
        remaining = repo.load_sitemap_data(website=website, n_limit=1)
        if not remaining:
            logger.info("[%s] queue drained after %d pass(es)", website, attempt - 1)
            return
        logger.info("[%s] pass %d: queue not empty, crawling newsdetails...", website, attempt)
        try:
            service.crawl_newsdetails(website)
        except Exception as e:
            logger.error("[%s] pass %d failed: %s", website, attempt, e)
            # Stop this source on hard failure to avoid a tight error loop.
            return
    logger.warning("[%s] hit max-passes=%d; queue may still have entries", website, max_passes)


def main():
    parser = argparse.ArgumentParser(description="Backfill articles for article-less sitemaps")
    parser.add_argument("--website", help="Single source to backfill (default: all)")
    parser.add_argument("--max-passes", type=int, default=50,
                        help="Safety cap on crawl passes per source (default: 50)")
    args = parser.parse_args()

    websites = [args.website] if args.website else DEFAULT_WEBSITES
    logger.info("Backfilling %d source(s): %s", len(websites), ", ".join(websites))

    service, repo = build_service()
    for website in websites:
        drain_website(service, repo, website, args.max_passes)

    logger.info("Backfill complete.")


if __name__ == "__main__":
    main()
