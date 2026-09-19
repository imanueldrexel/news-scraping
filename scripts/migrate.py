#!/usr/bin/env python3
"""
OPS-05: run every scripts/migrate_*.sql not yet recorded in schema_migrations, in
the documented order (CLAUDE.md's "Schema migrations" list), so "run once, in this
order on a fresh DB" is executed by code instead of by memory. Records each applied
file in a schema_migrations(name, applied_at) table so a second run is a no-op.

Usage:
    python scripts/migrate.py                  # apply every unrecorded migration
    python scripts/migrate.py --dry-run         # show what would be applied, change nothing
    python scripts/migrate.py --seed-existing   # record every listed migration as already
                                                 # applied WITHOUT running its SQL

--seed-existing exists to bootstrap this tool onto a database that already has every
migration applied by hand (both newsaggregator and newsaggregator_test are in this
state as of 2026-09-16). The migration files are NOT idempotent as a set -- e.g.
migrate_articles_columns.sql's `ALTER TABLE articles ALTER COLUMN is_embedded TYPE
BOOLEAN ...` has no guard against running twice -- so this tool never blindly
re-applies a file it has no record of; it only ever runs a file once, the first time
it sees no schema_migrations row for it.

Uses the same POSTGRES_DB_* env vars as SQLAlchemyClient (loaded from .env).
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

import psycopg2

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Documented order -- keep in sync with CLAUDE.md's "Schema migrations" list.
MIGRATIONS = [
    "migrate_phase1.sql",
    "migrate_articles_columns.sql",
    "migrate_sitemap_crawl_attempt.sql",
    "migrate_phase2.sql",
    "migrate_phase3.sql",
    "migrate_phase4.sql",
    "migrate_phase5.sql",
    "migrate_articles_unique_sitemap.sql",
    "migrate_extracted_text_prose.sql",
    "migrate_sitemap_crawl_status.sql",
    "migrate_knowledge_extract_attempts.sql",
    "migrate_chunks_unique.sql",
    "migrate_sitemap_fetch_failures.sql",
    "migrate_sitemaps_unique_link.sql",
]

# Superseded/dead files kept in scripts/ for reference only -- excluded from both the
# pending list and the "unknown migrate_*.sql file" warning below.
#   migrate_posted_at.sql: converts sitemaps.posted_at TIMESTAMP -> INTEGER "after the
#   database was created with init.sql" -- init.sql doesn't exist in this repo (it was
#   the orphaned worktree-phase1-migration branch's own bootstrap flow, never adopted;
#   see EXPERIMENTS.md's "is the orphaned worktree branch still needed" entry), and
#   sitemaps.posted_at is already INTEGER on both real databases via whatever created
#   the base schema. Running it now would fail (posted_at is already an int, not a
#   timestamp, so the USING cast has nothing to convert from).
IGNORED_MIGRATIONS = {"migrate_posted_at.sql"}


def _connect():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_DB_HOST", "localhost"),
        port=os.getenv("POSTGRES_DB_PORT", 5431),
        user=os.getenv("POSTGRES_DB_USER", "postgres"),
        password=os.getenv("POSTGRES_DB_PASS", "postgres"),
        dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"),
    )


def _ensure_schema_migrations_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def _already_applied(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be applied, change nothing")
    parser.add_argument("--seed-existing", action="store_true",
                        help="Record every unrecorded migration as already applied WITHOUT running its SQL")
    args = parser.parse_args()

    conn = _connect()
    conn.autocommit = False
    try:
        _ensure_schema_migrations_table(conn)
        applied = _already_applied(conn)

        unknown_files = sorted(
            f for f in os.listdir(SCRIPTS_DIR)
            if f.startswith("migrate_") and f.endswith(".sql")
            and f not in MIGRATIONS and f not in IGNORED_MIGRATIONS
        )
        if unknown_files:
            logger.warning("migrate_*.sql file(s) not in this script's MIGRATIONS list -- add them: %s",
                            ", ".join(unknown_files))

        pending = [m for m in MIGRATIONS if m not in applied]
        if not pending:
            logger.info("Nothing to do -- all %d known migrations are recorded.", len(MIGRATIONS))
            return 0

        logger.info("Pending (%d): %s", len(pending), ", ".join(pending))
        if args.dry_run:
            logger.info("[dry-run] Not applying anything.")
            return 0

        for name in pending:
            with conn.cursor() as cur:
                if args.seed_existing:
                    logger.info("Marking %s as already applied (not run)", name)
                else:
                    logger.info("Applying %s ...", name)
                    sql = open(os.path.join(SCRIPTS_DIR, name), encoding="utf-8").read()
                    cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
            conn.commit()

        logger.info("Done.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
