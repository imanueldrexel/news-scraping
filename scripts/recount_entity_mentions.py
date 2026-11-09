#!/usr/bin/env python3
"""
SYS-20 (#41): recompute entities.mention_count / first_seen_at / last_seen_at
from entity_mentions, once, for the drift written before the fix (an alias hit
never counted, a duplicate in one article or a retry counted twice, and an
older article moved last_seen_at back). Since the fix, insert_entity_mention
keeps the three in step, so a clean run of this reports 0 and changes nothing.

Usage:
    python scripts/recount_entity_mentions.py --dry-run   # report the drift
    python scripts/recount_entity_mentions.py             # back up, then fix

The real run writes the drifting rows' current values to
backups/sys20_entity_counts_<UTC>.json before the UPDATE, in one transaction.
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")

# DBT-67 (ADR-015): the recount is shared by the store repairs. Its backups go to
# store_repair.BACKUP_DIR (redirect that, not a copy here).
from newscrawler.tools.store_repair import ENTITY_DRIFT_SQL as DRIFT_SQL, recount_entity_counts  # noqa: E402,F401 (DRIFT_SQL: the tests' selection)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report the drift, change nothing")
    args = parser.parse_args(argv)

    return recount_entity_counts(SQLAlchemyClient(), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
