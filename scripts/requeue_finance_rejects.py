#!/usr/bin/env python3
"""
SYS-35 (#118, fix 2): re-queue the `rejected_filter` sitemaps whose category is
a dedicated finance/economy section.

Until SYS-35 the semantic score alone decided those rows, and it permanently
rejected 30-55% of every outlet's finance section (world oil prices 0.254,
Boeing shares 0.203, BI/QRIS 0.288). The category gate is symmetric now --
`is_news_category` short-circuits `is_important` to True -- so a re-fetch of
these rows saves them; the body was never stored, so a re-fetch is the only
way back. Which categories count is `is_finance_category()` from
`newscrawler.core.importance_filter`, imported, never re-listed here.

Only the finance-section rows. General-section rejects (`news`, `nasional`,
regional buckets) are SYS-38's (#122) job once the probe exists: on those the
category alone does not say news-worthy.

What the real run does, in one transaction after a JSON backup to backups/:
    crawl_status       'rejected_filter' -> 'pending'
    last_crawl_attempt  <stamp>          -> NULL   (else the 7-day cooldown
                                                    hides them for a week)
`fetch_failures` is left alone (these rows fetched fine; the filter said no).

Nothing is fetched by this script. The rows re-enter `load_all_sitemaps`'
queue for the next `task=full_text` on their source -- which, per the
HANDOFF hard rules, is allowed today only on the eight finance-narrowed
sources; the others wait for SYS-37.

Usage:
    python scripts/requeue_finance_rejects.py --dry-run [--website A,B]
    python scripts/requeue_finance_rejects.py [--website A,B] [--keep-cooldown]
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

from newscrawler.core.importance_filter import is_finance_category

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

_CANDIDATES_SQL = text("""
    SELECT sitemap_id, sources, category, last_crawl_attempt, fetch_failures
    FROM sitemaps
    WHERE crawl_status = 'rejected_filter'
      AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = sitemaps.sitemap_id)
      AND (:websites IS NULL OR sources = ANY(:websites))
    ORDER BY sitemap_id
""")
_REQUEUE_SQL = text("""
    UPDATE sitemaps
    SET crawl_status = 'pending',
        last_crawl_attempt = CASE WHEN :reset_cooldown THEN NULL ELSE last_crawl_attempt END
    WHERE sitemap_id = ANY(:ids) AND crawl_status = 'rejected_filter'
""")


def find_finance_rejects(session, websites=None):
    """(targets, by_source_category). targets: sitemap_ids whose category is a
    finance section per the live filter's own is_finance_category()."""
    rows = session.execute(_CANDIDATES_SQL, {"websites": websites}).fetchall()
    targets = []
    by_key = {}
    for r in rows:
        if not is_finance_category(r.category):
            continue
        targets.append(r.sitemap_id)
        key = (r.sources, r.category)
        by_key[key] = by_key.get(key, 0) + 1
    return targets, by_key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report counts per (source, category); change nothing")
    parser.add_argument("--website", default=None, help="Comma-separated sources (default: all)")
    parser.add_argument("--keep-cooldown", action="store_true",
                        help="Leave last_crawl_attempt as is (rows wait out the cooldown before re-offer)")
    args = parser.parse_args(argv)
    websites = [w.strip().upper() for w in args.website.split(",") if w.strip()] if args.website else None

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        targets, by_key = find_finance_rejects(session, websites)

    logger.info("%d rejected_filter row(s) under finance categories to re-queue", len(targets))
    for (source, category), n in sorted(by_key.items(), key=lambda kv: -kv[1]):
        logger.info("  %-16s %-24s %5d", source, category, n)
    if not targets:
        logger.info("Nothing to do.")
        return 0
    if args.dry_run:
        logger.info("[dry-run] Would set crawl_status='pending'%s on %d row(s).",
                    "" if args.keep_cooldown else " and last_crawl_attempt=NULL", len(targets))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"sys35_requeue_finance_rejects_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with client.get_session() as session:
        rows = session.execute(
            text("SELECT sitemap_id, sources, category, crawl_status, last_crawl_attempt "
                 "FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": targets}).fetchall()
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([dict(r._mapping) for r in rows], f, default=str, indent=2)
    logger.info("Backed up %d row(s) to %s", len(rows), backup_path)

    with client.get_session() as session:
        updated = session.execute(_REQUEUE_SQL, {"ids": targets, "reset_cooldown": not args.keep_cooldown}).rowcount
        session.commit()
    logger.info("Re-queued %d row(s)%s.", updated, "" if args.keep_cooldown else " (cooldown cleared)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
