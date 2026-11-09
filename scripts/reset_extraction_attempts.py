#!/usr/bin/env python3
"""
OPS-09 (#63): bring articles retired by SYS-19's knowledge_extract_attempts cap
back into get_articles_pending_extraction's queue. Retirement is otherwise
permanent -- nothing else resets the counter, and a retired article still counts
as `knowledge_extracted = 0` in the plain progress query, so it looks pending
forever without this.

Resets knowledge_extract_attempts to 0 and clears last_extract_error for the
matched rows. Use after fixing whatever caused the failures: a prompt/schema
change, a GEMINI_API_KEY rotation, or (before OPS-09 landed) an API outage that
was miscounted as a per-article failure.

Usage:
    python scripts/reset_extraction_attempts.py --dry-run --all-retired
    python scripts/reset_extraction_attempts.py --all-retired
    python scripts/reset_extraction_attempts.py --like "%503%"
    python scripts/reset_extraction_attempts.py --sitemap-ids 123,456
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _build_where(args):
    clauses = ["knowledge_extracted = 0", "knowledge_extract_attempts > 0"]
    params = {}
    if args.all_retired:
        clauses.append("knowledge_extract_attempts >= :max_attempts")
        params["max_attempts"] = KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
    if args.like:
        clauses.append("last_extract_error LIKE :pattern")
        params["pattern"] = args.like
    if args.sitemap_ids:
        clauses.append("sitemap_id = ANY(:sitemap_ids)")
        params["sitemap_ids"] = args.sitemap_ids
    return " AND ".join(clauses), params


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all-retired", action="store_true",
                         help=f"Match every article at/above the attempt cap (default {KNOWLEDGE_EXTRACT_MAX_ATTEMPTS})")
    parser.add_argument("--like", default=None, help="Only rows whose last_extract_error matches this SQL LIKE pattern")
    parser.add_argument("--sitemap-ids", type=lambda s: [int(x) for x in s.split(",") if x.strip()], default=None,
                         help="Comma-separated sitemap_ids to reset, regardless of attempt count")
    parser.add_argument("--dry-run", action="store_true", help="Report the matched count without writing")
    args = parser.parse_args()

    if not (args.all_retired or args.like or args.sitemap_ids):
        parser.error("Specify at least one of --all-retired, --like, or --sitemap-ids "
                      "(refusing to reset every failed attempt with no filter)")

    where_sql, params = _build_where(args)
    client = SQLAlchemyClient()

    with client.get_session() as session:
        count = session.execute(
            text(f"SELECT COUNT(*) FROM articles WHERE {where_sql}"), params
        ).scalar()

        if args.dry_run:
            print(f"[dry-run] Would reset {count} article(s) matching: {where_sql} {params}")
            return

        if count == 0:
            print("No matching articles -- nothing to reset.")
            return

        session.execute(
            text(f"""
                UPDATE articles
                SET knowledge_extract_attempts = 0, last_extract_error = NULL
                WHERE {where_sql}
            """),
            params,
        )
        session.commit()
        print(f"Reset {count} article(s). They are now eligible for get_articles_pending_extraction again.")


if __name__ == "__main__":
    main()
