#!/usr/bin/env python3
"""
SRC-36 (#129) / SRC-41 (#135): rewrite `sitemaps.category` rows that hold a
sitemap-index URL instead of a section name.

Three crawlers built their branch key with `re.sub` on a pattern the live index
no longer matched; a non-matching `re.sub` returns its input unchanged, so the
full `<loc>` URL became the branch key and then the stored category -- CNN 682
rows, JPNN 6,104 rows. The category deny-list (`is_offtopic_category`) is
exact-match for half its vocabulary and SRC-35's soft-branch helper works on
the key, so both are blind to those rows until they are names.

The new name for each stored URL comes from the crawler's own
`branch_name_from_url()` -- the same function `_get_branches` now uses -- never
from a regex re-derived here, so the repaired value is exactly the key a fresh
crawl would write today. A URL that function cannot name is reported and left
alone; nothing is guessed.

Ordering, same as cleanup_offtopic_articles.py: JSON backup of every
(sitemap_id, category) about to change to backups/, then all UPDATEs in ONE
transaction. Idempotent: re-running after success finds 0 rows.

Not touched: FAISS docstore `metadata.category` for the rows that already have
an article (display-only in RAG hits; the UI's category filter is a substring
match, so `ekonomi` still matches the old URL string there).

Usage:
    python scripts/fix_url_shaped_categories.py --dry-run [--website CNN,JPNN]
    python scripts/fix_url_shaped_categories.py [--website CNN,JPNN]
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# Only crawlers whose branch key is a section name derived from the <loc>
# through a single shared function may be repaired here.
DEFAULT_WEBSITES = ("CNN", "JPNN")

_DISTINCT_SQL = text("""
    SELECT category, COUNT(*) AS n,
           COUNT(*) FILTER (WHERE crawl_status = 'rejected_filter') AS rejected
    FROM sitemaps
    WHERE sources = :src AND category LIKE 'http%'
    GROUP BY category ORDER BY n DESC
""")
_BACKUP_SQL = text("""
    SELECT sitemap_id, sources, category FROM sitemaps
    WHERE sources = :src AND category LIKE 'http%'
""")
_UPDATE_SQL = text("UPDATE sitemaps SET category = :new WHERE sources = :src AND category = :old")
_REMAINING_SQL = text("SELECT COUNT(*) FROM sitemaps WHERE sources = :src AND category LIKE 'http%'")


def _namer(website: str):
    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    crawler = CRAWLER_DICT.get(website)
    if crawler is None:
        raise SystemExit(f"{website}: not a registered crawler")
    namer = getattr(crawler, "branch_name_from_url", None)
    if namer is None:
        raise SystemExit(f"{website}: crawler has no branch_name_from_url(); nothing to repair it with")
    return namer


def plan(session, website: str, namer) -> Tuple[List[Tuple[str, str, int, int]], List[Tuple[str, int]]]:
    """(mapped, unmappable). mapped: (old_url, new_name, rows, rejected_rows);
    unmappable: (old_url, rows) the crawler cannot name -- left untouched."""
    mapped, unmappable = [], []
    for row in session.execute(_DISTINCT_SQL, {"src": website}).fetchall():
        new = namer(row.category)
        if new is None or new.startswith("http"):
            unmappable.append((row.category, row.n))
        else:
            mapped.append((row.category, new, row.n, row.rejected))
    return mapped, unmappable


def _report(website: str, mapped, unmappable) -> int:
    total = sum(n for _, _, n, _ in mapped)
    logger.info("%s: %d distinct URL-shaped categories -> %d row(s) to rewrite, %d distinct unmappable",
                website, len(mapped), total, len(unmappable))
    for old, new, n, rejected in mapped:
        logger.info("  %-70s -> %-24s %5d rows (%d rejected_filter)", old, new, n, rejected)
    for old, n in unmappable:
        logger.warning("  UNMAPPABLE (left as is): %-60s %5d rows", old, n)
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print the mapping table and counts; change nothing")
    parser.add_argument("--website", default=",".join(DEFAULT_WEBSITES),
                        help=f"Comma-separated sources to repair (default {','.join(DEFAULT_WEBSITES)})")
    args = parser.parse_args(argv)
    websites = [w.strip().upper() for w in args.website.split(",") if w.strip()]

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()

    plans: Dict[str, list] = {}
    grand_total = 0
    with client.get_session() as session:
        db = session.execute(text("SELECT current_database()")).scalar()
        logger.info("database: %s", db)
        for website in websites:
            mapped, unmappable = plan(session, website, _namer(website))
            plans[website] = mapped
            grand_total += _report(website, mapped, unmappable)

    if grand_total == 0:
        logger.info("Nothing to do.")
        return 0
    if args.dry_run:
        logger.info("[dry-run] Would rewrite %d sitemaps.category row(s) across %s.", grand_total, ", ".join(websites))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, f"src36_url_shaped_categories_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )
    with client.get_session() as session:
        backup = {w: [dict(r._mapping) for r in session.execute(_BACKUP_SQL, {"src": w}).fetchall()] for w in websites}
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, default=str, indent=2)
    logger.info("Backed up %d row(s) to %s", sum(len(v) for v in backup.values()), backup_path)

    with client.get_session() as session:
        rewritten = 0
        for website, mapped in plans.items():
            for old, new, _, _ in mapped:
                rewritten += session.execute(_UPDATE_SQL, {"src": website, "old": old, "new": new}).rowcount
        session.commit()
    logger.info("Rewrote %d row(s) in one transaction.", rewritten)

    with client.get_session() as session:
        for website in websites:
            remaining = session.execute(_REMAINING_SQL, {"src": website}).scalar()
            logger.info("%s: %d URL-shaped category row(s) remaining", website, remaining)
    return 0


if __name__ == "__main__":
    sys.exit(main())
