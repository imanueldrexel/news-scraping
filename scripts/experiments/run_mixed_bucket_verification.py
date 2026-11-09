#!/usr/bin/env python3
"""
SYS-37 (#121) Done-when: "a real task=full_text over >= 200 rows of one mixed
bucket, read by hand: no recipe/prayer/horoscope/gossip/listicle/sport in the
saves, and topics plausible on a 50-row sample."

Runs the REAL save path (CrawlerServiceImpl.crawl_newsdetails with
specific_sitemaps) over the N newest pending rows of one (source, category)
bucket, then prints what was saved and what was rejected, with topic and
P(soft), for the hand-read. This writes articles/chunks/FAISS/crawl_log like any
crawl -- run it only with the owner's go, and only on a source the HANDOFF
allows. --dry-run lists the rows it would fetch and exits.

    python scripts/experiments/run_mixed_bucket_verification.py --website CNBC --category news --limit 200 --dry-run
    python scripts/experiments/run_mixed_bucket_verification.py --website CNBC --category news --limit 200
"""
import argparse
import collections
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_PENDING_SQL = text("""
    SELECT sitemap_id, headline, link, category, sources, posted_at, keywords
    FROM sitemaps
    WHERE sources = :src AND lower(category) = lower(:cat) AND crawl_status = 'pending'
      AND (last_crawl_attempt IS NULL OR last_crawl_attempt < now() - interval '7 days')
      AND fetch_failures < 3
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = sitemaps.sitemap_id)
    ORDER BY posted_at DESC, sitemap_id DESC
    LIMIT :n
""")
_RESULT_SQL = text("""
    SELECT s.sitemap_id, s.headline, s.crawl_status, a.topic, a.topic_confidence
    FROM sitemaps s LEFT JOIN articles a USING (sitemap_id)
    WHERE s.sitemap_id = ANY(:ids)
    ORDER BY a.topic NULLS LAST, s.sitemap_id
""")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    client = SQLAlchemyClient()
    with client.get_session() as s:
        logger.info("database: %s", s.execute(text("SELECT current_database()")).scalar())
        rows = s.execute(_PENDING_SQL, {"src": args.website.upper(), "cat": args.category, "n": args.limit}).fetchall()
    logger.info("%d pending %s/%s rows selected (newest first)", len(rows), args.website, args.category)
    if not rows:
        return 0
    if args.dry_run:
        for r in rows[:15]:
            logger.info("  %s %s  %s", r.sitemap_id, r.posted_at, (r.headline or "")[:90])
        logger.info("[dry-run] nothing fetched, nothing written.")
        return 0

    from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
    api = init_crawler()
    dtos = [SitemapDTO(headline=r.headline, link=r.link, sources=r.sources, category=r.category,
                       timestamp=r.posted_at, keywords=r.keywords, sitemap_id=r.sitemap_id) for r in rows]
    api.crawler_service.crawl_newsdetails(args.website.upper(), specific_sitemaps=dtos)

    with client.get_session() as s:
        res = s.execute(_RESULT_SQL, {"ids": [r.sitemap_id for r in rows]}).fetchall()
    by_status = collections.Counter(r.crawl_status for r in res)
    logger.info("outcome: %s", dict(by_status))
    saved = [r for r in res if r.topic is not None]
    logger.info("SAVED %d -- topic distribution: %s", len(saved), dict(collections.Counter(r.topic for r in saved)))
    for r in saved:
        logger.info("  SAVED  %-20s %.2f  %s", r.topic, r.topic_confidence or 0, (r.headline or "")[:95])
    rejected = [r for r in res if r.crawl_status == "rejected_filter"]
    logger.info("REJECTED %d", len(rejected))
    for r in rejected:
        logger.info("  REJECT %s", (r.headline or "")[:95])
    return 0


if __name__ == "__main__":
    sys.exit(main())
