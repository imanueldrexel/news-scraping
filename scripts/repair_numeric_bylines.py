#!/usr/bin/env python3
"""
SRC-10 (#65): repair `articles.writer` rows whose byline is not a name.

Before 7cba3bf, IDXCHANNEL's reporter selector matched the timestamp element,
so every article stored the publication day as its author (`["16"]`). The
selector and the shared guard (`Crawler._looks_like_a_name`) fixed new rows;
the old ones still carry the number, and a plausible non-null value is exactly
what no "missing byline" check can see.

Selection: articles whose `writer` holds at least one entry the crawler's own
guard rejects (all digits, or a date). For each, the page is re-fetched through
its crawler's page loader, one request per `--interval` seconds, and the byline
is read with the crawler's current `_get_reporter_from_text` plus the guard.
The new value is the names found, or `[]` when the page fails or has no name:
unknown, not wrong. In one transaction, after a JSON backup to backups/.

Usage:
    python scripts/repair_numeric_bylines.py --dry-run --limit 5   # fetch 5, show, write nothing
    python scripts/repair_numeric_bylines.py --dry-run --no-fetch  # count only
    python scripts/repair_numeric_bylines.py                        # fetch all, back up, write
    python scripts/repair_numeric_bylines.py --no-fetch             # write [] for all, no network
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# Narrowed in SQL to rows with a digit in `writer`; the guard decides in Python.
_CANDIDATES_SQL = text("""
    SELECT a.articles_id, a.sitemap_id, a.writer, s.sources, s.link
    FROM articles a JOIN sitemaps s USING (sitemap_id)
    WHERE a.writer::text ~ '[0-9]' AND (:website IS NULL OR s.sources = :website)
    ORDER BY a.articles_id
""")
_UPDATE_SQL = text("UPDATE articles SET writer = CAST(:writer AS JSON) WHERE articles_id = :id")


def is_bad_byline(writer) -> bool:
    """True when some entry of `writer` is not a name by the crawler's guard."""
    return isinstance(writer, list) and any(
        not isinstance(w, str) or not Crawler._looks_like_a_name(w) for w in writer)


def find_candidates(session, website=None):
    rows = session.execute(_CANDIDATES_SQL, {"website": website}).fetchall()
    return [r for r in rows if is_bad_byline(r.writer)]


def refetch_byline(crawler, link):
    """Names on the live page, or [] when it fails or names nobody."""
    soup = crawler.page_loader.get_soup(link)
    if not soup:
        return []
    try:
        return [r for r in crawler._get_reporter_from_text(soup) if crawler._looks_like_a_name(r)]
    except Exception as e:  # noqa: BLE001 -- one page must not stop the repair
        logger.warning("byline extraction raised for %s: %r", link, e)
        return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="Do not re-fetch; the new value is [] for every row")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between page fetches")
    args = parser.parse_args(argv)

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = find_candidates(session, args.website)
    by_source = {}
    for r in rows:
        by_source[r.sources] = by_source.get(r.sources, 0) + 1
    logger.info("%d article(s) with a byline that is not a name: %s", len(rows), by_source)
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        return 0

    new_values = {}
    if args.no_fetch:
        new_values = {r.articles_id: [] for r in rows}
    else:
        from newscrawler.core.crawler_dict_list import CRAWLER_DICT
        for i, r in enumerate(rows):
            new_values[r.articles_id] = refetch_byline(CRAWLER_DICT[r.sources], r.link)
            if i < 10 or args.dry_run:
                logger.info("  %s %s -> %s", r.writer, r.link, new_values[r.articles_id])
            time.sleep(args.interval)
    named = sum(1 for v in new_values.values() if v)
    logger.info("%d of %d get a real name, %d get [] (unknown)", named, len(rows), len(rows) - named)
    if args.dry_run:
        logger.info("[dry-run] Nothing written.")
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"src10_bylines_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"articles_id": r.articles_id, "sitemap_id": r.sitemap_id, "writer": r.writer,
                    "new_writer": new_values[r.articles_id]} for r in rows], f, indent=2)
    logger.info("Backed up %d row(s) to %s", len(rows), path)
    with client.get_session() as session:
        for articles_id, writer in new_values.items():
            session.execute(_UPDATE_SQL, {"id": articles_id, "writer": json.dumps(writer)})
        session.commit()
        left = len(find_candidates(session, args.website))
    logger.info("Updated %d row(s); bylines that are not a name left: %d", len(new_values), left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
