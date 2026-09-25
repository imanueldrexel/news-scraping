#!/usr/bin/env python3
"""
SRC-51 (#163): rewrite `sitemaps.posted_at` from the date in the article's own
URL, for a source whose sitemap dates are known to be wrong.

OKEZONE stamps every <news:publication_date> with the time its sitemap was
rendered, so until the crawler fix every stored OKEZONE row had the CRAWL date:
2,299 rows, 2 distinct `posted_at` values, URLs running from /2026/08/14/ to
/2026/09/24/. The new value for each row comes from the crawler's own
`date_from_url(link)`, the function `_get_timestamp` uses now, so a repaired row
holds exactly what a fresh crawl would write. A link it cannot date is reported
and left alone. Nothing is guessed.

Scope: `sitemaps` only. `posted_at` is also copied into `articles.meta_data` and
the FAISS docstore metadata when an article is saved, and those copies are NOT
rewritten here. So the script REFUSES (exit 3) if any row it would change
already has an `articles` row. Today OKEZONE has none, and running this before
its first `task=full_text` keeps it that way.

`sitemaps_link_uq` makes the link a row's identity (SYS-29), so changing
`posted_at` cannot create or merge rows. `probe_sitemap_dedup_drift.py
--website OKEZONE` (2026-09-25): would_insert_duplicate=0.

Ordering (same discipline as repair_stale_branch_categories.py): dry run, then a
JSON backup of every (sitemap_id, old posted_at), then all UPDATEs in ONE
transaction. Idempotent: a second run finds 0 rows.

    python scripts/repair_posted_at_from_url.py --dry-run [--website OKEZONE]
    python scripts/repair_posted_at_from_url.py            # after the owner's go
"""
import argparse
import collections
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# Only crawlers whose URLs carry the date and whose sitemap dates are known wrong.
DEFAULT_WEBSITES = ("OKEZONE",)

_ROWS_SQL = text("""
    SELECT s.sitemap_id, s.link, s.posted_at, (a.sitemap_id IS NOT NULL) AS has_article
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE s.sources = :src ORDER BY s.sitemap_id
""")


def plan(rows, date_from_url):
    """(changes, undatable) -- pure, for the tests.

    changes: (sitemap_id, old posted_at, new posted_at, has_article) for rows
    whose URL date differs from what is stored."""
    changes, undatable = [], []
    for r in rows:
        dt = date_from_url(r.link)
        if dt is None:
            undatable.append((r.sitemap_id, r.link))
            continue
        new = int(dt.strftime("%Y%m%d"))
        if new != r.posted_at:
            changes.append((r.sitemap_id, r.posted_at, new, bool(r.has_article)))
    return changes, undatable


def report(website, rows, changes, undatable):
    logger.info("%s: %d row(s) examined, %d to rewrite, %d already right, %d undatable by URL",
                website, len(rows), len(changes), len(rows) - len(changes) - len(undatable), len(undatable))
    logger.info("  distinct posted_at before: %d, after: %d", len({r.posted_at for r in rows}),
                len({new for _, _, new, _ in changes} | {r.posted_at for r in rows
                                                        if r.sitemap_id not in {c[0] for c in changes}}))
    moves = collections.Counter((old, new) for _, old, new, _ in changes)
    for (old, new), n in sorted(moves.items(), key=lambda kv: -kv[1])[:15]:
        logger.info("  %s -> %s  %5d", old, new, n)
    if undatable:
        logger.warning("  %d row(s) with no date in the URL -- left as is, e.g. %s", len(undatable),
                       undatable[0][1][:90])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing")
    ap.add_argument("--website", default=",".join(DEFAULT_WEBSITES))
    args = ap.parse_args(argv)

    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    client = SQLAlchemyClient()
    total = []
    for website in [w.strip().upper() for w in args.website.split(",") if w.strip()]:
        crawler = CRAWLER_DICT.get(website)
        if crawler is None or not hasattr(crawler, "date_from_url"):
            logger.error("%s: no crawler with a date_from_url to repair from", website)
            return 2
        with client.get_session() as session:
            logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
            rows = session.execute(_ROWS_SQL, {"src": website}).fetchall()
        changes, undatable = plan(rows, crawler.date_from_url)
        report(website, rows, changes, undatable)
        total.extend((website, *c) for c in changes)

    blocked = [c for c in total if c[4]]
    if blocked:
        logger.error("%d row(s) to change already have an articles row, whose meta_data.posted_at and FAISS "
                     "metadata this script does not rewrite -- refusing (e.g. sitemap_id %s)", len(blocked), blocked[0][1])
        return 3
    if not total:
        logger.info("Nothing to repair.")
        return 0
    if args.dry_run:
        logger.info("[dry-run] would UPDATE sitemaps.posted_at on %d row(s). Nothing written.", len(total))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, "src51_posted_at_from_url_%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as f:
        json.dump([{"sitemap_id": sid, "sources": src, "posted_at": old, "new_posted_at": new}
                   for src, sid, old, new, _ in total], f)
    logger.info("backup of the previous values written to %s", backup)

    with client.get_session() as session:
        n = 0
        for _, sid, old, new, _ in total:
            n += session.execute(text("UPDATE sitemaps SET posted_at = :new WHERE sitemap_id = :sid AND posted_at = :old"),
                                 {"new": new, "sid": sid, "old": old}).rowcount
        session.commit()
    logger.info("updated %d row(s) in one transaction.", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
