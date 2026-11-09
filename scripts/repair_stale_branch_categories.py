#!/usr/bin/env python3
"""
SRC-48 (#158): rewrite `sitemaps.category` rows that hold a BRANCH name where
the article's own section is available.

SRC-43 (#146) gave MEDIAINDONESIA real branch names, which made `_scrape`'s
`branch_name == link` test permanently false, so its per-article section stopped
being consulted and every row was stored under the branch name -- `news` for
almost all of them, a deliberately mixed bucket the deny-list cannot reject.
SRC-48 fixed the code; this repairs the rows written before it.

The new value for each row comes from the crawler's own
`_get_branch_name_from_url(link)` -- the same function `_scrape` now uses -- so a
repaired row holds exactly what a fresh crawl would write today. A link that
function cannot name, or that yields something unusable (empty, `http`-prefixed,
over 40 chars -- `Crawler.usable_section_name`), is reported and left alone.
Nothing is guessed.

Why this is not part of `fix_url_shaped_categories.py` (SRC-36/SRC-41): that
script maps ONE new name per distinct stored category value and updates with
`WHERE category = :old`. Here every row shares the same stored value (`news`)
and maps to a DIFFERENT section from its own link, so the mapping is per row and
the update is by `sitemap_id`. Bolting a second selection and update path into a
script that has already run against production twice is worse than a focused
one; the ordering discipline below is copied from it deliberately.

Ordering: dry-run first, then a JSON backup of every (sitemap_id, old category)
about to change, then all UPDATEs in ONE transaction. Idempotent: a second run
finds 0 rows.

    python scripts/repair_stale_branch_categories.py --dry-run [--website MEDIAINDONESIA]
    python scripts/repair_stale_branch_categories.py            # after the owner's go
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

from newscrawler.core.importance_filter import category_gate  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# Only crawlers that derive a per-article section are repairable here.
DEFAULT_WEBSITES = ("MEDIAINDONESIA",)

_ROWS_SQL = text("""
    SELECT sitemap_id, category, link, crawl_status
    FROM sitemaps WHERE sources = :src AND link IS NOT NULL
    ORDER BY sitemap_id
""")


def plan(rows, crawler):
    """(changes, unmappable) -- pure, for the tests.

    changes: (sitemap_id, old, new, crawl_status) for rows whose own link yields
    a usable section that differs from what is stored.
    """
    changes, unmappable = [], []
    for r in rows:
        derived = crawler._get_branch_name_from_url(r.link)
        if not crawler.usable_section_name(derived):
            if (r.category or "") != (derived or ""):
                unmappable.append((r.sitemap_id, r.category, r.link))
            continue
        if (r.category or "").strip() == derived.strip():
            continue
        changes.append((r.sitemap_id, r.category, derived, r.crawl_status))
    return changes, unmappable


def report(website, rows, changes, unmappable):
    logger.info("%s: %d row(s) examined, %d to rewrite, %d left alone (unnameable link)",
                website, len(rows), len(changes), len(unmappable))
    pairs = collections.Counter((old, new) for _, old, new, _ in changes)
    logger.info("  %-24s -> %-24s %6s  %s", "stored now", "article's own section", "rows", "gate change")
    for (old, new), n in pairs.most_common(30):
        logger.info("  %-24s -> %-24s %6d  %s -> %s", str(old), new, n,
                    category_gate(old, website), category_gate(new, website))
    by_status = collections.Counter(st for _, _, _, st in changes)
    logger.info("  by crawl_status: %s", dict(by_status))
    now_denied = sum(n for (old, new), n in pairs.items()
                     if category_gate(old, website) != "deny" and category_gate(new, website) == "deny")
    logger.info("  rows that become DENY at the category gate: %d", now_denied)
    if unmappable:
        logger.warning("  %d row(s) whose link the crawler cannot name -- left as is, e.g. %s",
                       len(unmappable), unmappable[0][2][:90])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print the mapping and counts; change nothing")
    ap.add_argument("--website", default=",".join(DEFAULT_WEBSITES))
    args = ap.parse_args(argv)

    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    client = SQLAlchemyClient()
    total_changes = []
    for website in [w.strip().upper() for w in args.website.split(",")]:
        crawler = CRAWLER_DICT.get(website)
        if crawler is None:
            logger.error("%s: not a registered crawler", website)
            return 2
        if not crawler.derives_category_from_url():
            logger.error("%s: crawler derives no per-article section; nothing to repair it with", website)
            return 2
        with client.get_session() as session:
            logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
            rows = session.execute(_ROWS_SQL, {"src": website}).fetchall()
        changes, unmappable = plan(rows, crawler)
        report(website, rows, changes, unmappable)
        total_changes.extend((website, *c) for c in changes)

    if not total_changes:
        logger.info("Nothing to repair.")
        return 0
    if args.dry_run:
        logger.info("[dry-run] would UPDATE sitemaps.category on %d row(s). Nothing written.", len(total_changes))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, f"src48_stale_branch_categories_{stamp}.json")
    with open(backup, "w", encoding="utf-8") as f:
        json.dump([{"sitemap_id": sid, "sources": src, "category": old, "new_category": new}
                   for src, sid, old, new, _ in total_changes], f)
    logger.info("backup of the previous values written to %s", backup)

    with client.get_session() as session:
        n = 0
        for _, sid, _, new, _ in total_changes:
            n += session.execute(text("UPDATE sitemaps SET category = :new WHERE sitemap_id = :sid"),
                                 {"new": new, "sid": sid}).rowcount
        session.commit()
    logger.info("updated %d row(s) in one transaction.", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
