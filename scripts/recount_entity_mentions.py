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
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")

# The entities whose stored counters disagree with their mentions, with both.
DRIFT_SQL = text("""
    SELECT e.entity_id, e.name, e.mention_count, e.first_seen_at, e.last_seen_at,
           COALESCE(m.n, 0) AS true_count, m.lo AS true_first, m.hi AS true_last
    FROM entities e
    LEFT JOIN (SELECT entity_id, COUNT(*) AS n, MIN(posted_at) AS lo, MAX(posted_at) AS hi
               FROM entity_mentions GROUP BY 1) m USING (entity_id)
    WHERE e.mention_count <> COALESCE(m.n, 0)
       OR e.first_seen_at IS DISTINCT FROM m.lo
       OR e.last_seen_at IS DISTINCT FROM m.hi
    ORDER BY e.entity_id
""")

FIX_SQL = text("""
    UPDATE entities e SET
        mention_count = (SELECT COUNT(*) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        first_seen_at = (SELECT MIN(posted_at) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        last_seen_at  = (SELECT MAX(posted_at) FROM entity_mentions m WHERE m.entity_id = e.entity_id),
        updated_at    = NOW()
    WHERE e.entity_id = ANY(:ids)
""")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report the drift, change nothing")
    args = parser.parse_args(argv)

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(DRIFT_SQL).fetchall()
        if not rows:
            logger.info("No drift: every entity's counters match entity_mentions.")
            return 0
        count_drift = sum(r.mention_count - r.true_count for r in rows)
        logger.info("%d entit(y/ies) drift; net mention_count drift %+d; e.g. %s", len(rows), count_drift,
                    "; ".join(f"{r.name!r} {r.mention_count}->{r.true_count}" for r in rows[:5]))
        if args.dry_run:
            logger.info("[dry-run] Would recompute %d entit(y/ies).", len(rows))
            return 0
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"sys20_entity_counts_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([dict(r._mapping) for r in rows], f, default=str, indent=2)
        logger.info("Backed up %d row(s) to %s", len(rows), path)
        session.execute(FIX_SQL, {"ids": [r.entity_id for r in rows]})
        session.commit()
        left = session.execute(DRIFT_SQL).fetchall()
    logger.info("Recomputed %d entit(y/ies); drift left: %d", len(rows), len(left))
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
