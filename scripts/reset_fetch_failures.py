#!/usr/bin/env python3
"""
OPS-15 (#81): bring sitemaps retired by SYS-09's fetch_failures cap back into
load_all_sitemaps' queue. Retirement is otherwise permanent -- nothing else resets
the counter -- and a retired sitemap still shows as crawl_status='pending', so it
looks like it is waiting its turn forever without this. Mirrors
scripts/reset_extraction_attempts.py (OPS-09) for the Gemini attempt cap.

Resets fetch_failures to 0 and clears last_fetch_error for the matched rows. Use
after fixing whatever caused the failures: a scraper fix (SRC-*), a site
un-blocking article pages, a TLS/DNS problem going away, or (before OPS-15's
whole-source guard landed) a source-wide outage that was miscounted as hundreds
of individually dead URLs.

A reset row still waits out SITEMAP_RECRAWL_COOLDOWN_DAYS from its last attempt
(the failure stamped last_crawl_attempt too); --clear-cooldown also nulls that so
the row is eligible on the very next run.

Usage:
    python scripts/reset_fetch_failures.py --dry-run --website KOMPAS
    python scripts/reset_fetch_failures.py --website KOMPAS
    python scripts/reset_fetch_failures.py --all-retired                # every source
    python scripts/reset_fetch_failures.py --like "HTTP 403%"           # one failure mode
    python scripts/reset_fetch_failures.py --sitemap-ids 123,456 --clear-cooldown
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _build_where(args):
    """Every filter narrows the base condition fetch_failures > 0 -- a row that
    never failed is never touched."""
    clauses = ["fetch_failures > 0"]
    params = {}
    if args.website:
        clauses.append("sources = :website")
        params["website"] = args.website
    if args.all_retired:
        clauses.append("fetch_failures >= :max_failures")
        params["max_failures"] = SITEMAP_MAX_FETCH_FAILURES
    if args.like:
        clauses.append("last_fetch_error LIKE :pattern")
        params["pattern"] = args.like
    if args.sitemap_ids:
        clauses.append("sitemap_id = ANY(:sitemap_ids)")
        params["sitemap_ids"] = args.sitemap_ids
    return " AND ".join(clauses), params


def _build_set(args):
    columns = ["fetch_failures = 0", "last_fetch_error = NULL"]
    if args.clear_cooldown:
        columns.append("last_crawl_attempt = NULL")
    return ", ".join(columns)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Only this source (sitemaps.sources)")
    parser.add_argument("--all-retired", action="store_true",
                        help=f"Only rows at/above the cap (SITEMAP_MAX_FETCH_FAILURES={SITEMAP_MAX_FETCH_FAILURES}), "
                             f"i.e. the ones load_all_sitemaps has stopped offering")
    parser.add_argument("--like", default=None, help="Only rows whose last_fetch_error matches this SQL LIKE pattern")
    parser.add_argument("--sitemap-ids", type=lambda s: [int(x) for x in s.split(",") if x.strip()], default=None,
                        help="Comma-separated sitemap_ids to reset, regardless of their count")
    parser.add_argument("--clear-cooldown", action="store_true",
                        help="Also NULL last_crawl_attempt so the rows are eligible on the next run, not after the cooldown")
    parser.add_argument("--dry-run", action="store_true", help="Report the matched count per source without writing")
    args = parser.parse_args(argv)

    if not (args.website or args.all_retired or args.like or args.sitemap_ids):
        parser.error("Specify at least one of --website, --all-retired, --like, or --sitemap-ids "
                     "(refusing to reset every failed fetch with no filter)")

    where_sql, params = _build_where(args)
    client = SQLAlchemyClient()

    with client.get_session() as session:
        rows = session.execute(
            text(f"SELECT sources, COUNT(*) AS n, MAX(fetch_failures) AS worst FROM sitemaps "
                 f"WHERE {where_sql} GROUP BY sources ORDER BY n DESC"),
            params,
        ).fetchall()
        count = sum(r.n for r in rows)
        per_source = ", ".join(f"{r.sources}: {r.n} (worst {r.worst})" for r in rows) or "none"

        if args.dry_run:
            print(f"[dry-run] Would reset {count} sitemap(s) -- {per_source}\n          WHERE {where_sql} {params}")
            return 0

        if count == 0:
            print("No matching sitemaps -- nothing to reset.")
            return 0

        session.execute(text(f"UPDATE sitemaps SET {_build_set(args)} WHERE {where_sql}"), params)
        session.commit()
        print(f"Reset {count} sitemap(s) -- {per_source}. "
              + ("Eligible for load_all_sitemaps on the next run." if args.clear_cooldown
                 else "Eligible again once their cooldown has elapsed (or re-run with --clear-cooldown)."))
        return 0


if __name__ == "__main__":
    sys.exit(main())
