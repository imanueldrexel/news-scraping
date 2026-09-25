#!/usr/bin/env python3
"""
SRC-50 (#162) / SYS-50 (#165): mark queued sitemaps whose CATEGORY the gate
denies as `rejected_filter`, without fetching them.

`category_gate` decides `deny` from `sitemaps.category` alone, which is known at
listing time. Until SYS-50 moves that decision in front of the fetch, every
queued row in a denied category costs a full page fetch and extraction only to
be rejected on information we already had. And when a category starts being
denied (SRC-50's 58 DETIK leaves), rows already listed under it stay `pending`
until a crawl gets round to them. This settles them now.

Selection is the article queue's own (`load_all_sitemaps`): no `articles` row
and `crawl_status != 'rejected_filter'`. The cooldown and fetch-failure cap are
deliberately NOT applied, because a denied row is denied whenever it would come
up. The decision is exactly the live one: `category_gate(category, source) == 'deny'`,
the same function `classify_batch` calls first. Nothing is embedded or scored.

Ordering (same discipline as repair_stale_branch_categories.py): dry run, then
a JSON backup of every (sitemap_id, crawl_status) about to change, then one
UPDATE in one transaction, guarded on the old status. Idempotent: a second run
finds 0 rows. `--revert <backup>` puts every row back to its backed-up status.

    python scripts/reject_denied_categories.py --dry-run --website DETIK
    python scripts/reject_denied_categories.py --website DETIK      # after the owner's go
    python scripts/reject_denied_categories.py --revert backups/reject_denied_categories_<stamp>.json
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

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

_QUEUED_SQL = """
    SELECT s.sitemap_id, s.sources, s.category, s.crawl_status
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE a.sitemap_id IS NULL AND s.crawl_status != 'rejected_filter'
      AND s.category IS NOT NULL {website_clause}
    ORDER BY s.sitemap_id
"""


def plan(rows):
    """Rows whose category the live gate denies -- pure, for the tests. One gate
    call per distinct (source, category), since the decision depends on nothing
    else (the source scopes SRC-50's per-source leaves)."""
    verdict = {}
    out = []
    for r in rows:
        key = (r.sources, r.category)
        if key not in verdict:
            verdict[key] = category_gate(r.category, r.sources) == "deny"
        if verdict[key]:
            out.append(r)
    return out


def report(rows, denied):
    logger.info("%d queued row(s) examined, %d in a denied category", len(rows), len(denied))
    by_pair = collections.Counter((r.sources, r.category) for r in denied)
    for (src, cat), n in by_pair.most_common(80):
        logger.info("  %-15s %-40s %6d", src, cat, n)
    if len(by_pair) > 80:
        logger.info("  ... +%d more (source, category) pairs", len(by_pair) - 80)
    logger.info("  by source: %s", dict(collections.Counter(r.sources for r in denied).most_common()))
    logger.info("  by crawl_status now: %s", dict(collections.Counter(r.crawl_status for r in denied)))


def _revert(client, path):
    with open(path, encoding="utf-8") as f:
        backup = json.load(f)
    by_status = collections.defaultdict(list)
    for row in backup:
        by_status[row["crawl_status"]].append(row["sitemap_id"])
    with client.get_session() as session:
        n = 0
        for status, ids in by_status.items():
            n += session.execute(text(
                "UPDATE sitemaps SET crawl_status = :st WHERE sitemap_id = ANY(:ids) "
                "AND crawl_status = 'rejected_filter'"), {"st": status, "ids": ids}).rowcount
        session.commit()
    logger.info("reverted %d of %d row(s) from %s", n, len(backup), path)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing")
    ap.add_argument("--website", default=None, help="Comma-separated sources (default: every source)")
    ap.add_argument("--revert", metavar="BACKUP_JSON", help="Restore the statuses a previous run backed up")
    args = ap.parse_args(argv)

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    if args.revert:
        return _revert(client, args.revert)

    params, clause = {}, ""
    if args.website:
        params["sources"] = [w.strip().upper() for w in args.website.split(",") if w.strip()]
        clause = "AND s.sources = ANY(:sources)"
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(text(_QUEUED_SQL.format(website_clause=clause)), params).fetchall()
    denied = plan(rows)
    report(rows, denied)
    if not denied:
        logger.info("Nothing to reject.")
        return 0
    if args.dry_run:
        logger.info("[dry-run] would set crawl_status='rejected_filter' on %d row(s). Nothing written.", len(denied))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = os.path.join(BACKUP_DIR, "reject_denied_categories_%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as f:
        json.dump([{"sitemap_id": r.sitemap_id, "sources": r.sources, "category": r.category,
                    "crawl_status": r.crawl_status} for r in denied], f)
    logger.info("backup of the previous statuses written to %s", backup)

    by_status = collections.defaultdict(list)
    for r in denied:
        by_status[r.crawl_status].append(r.sitemap_id)
    with client.get_session() as session:
        n = 0
        for status, ids in by_status.items():
            n += session.execute(text(
                "UPDATE sitemaps SET crawl_status = 'rejected_filter' "
                "WHERE sitemap_id = ANY(:ids) AND crawl_status = :old"), {"ids": ids, "old": status}).rowcount
        session.commit()
    logger.info("set rejected_filter on %d row(s) in one transaction.", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
