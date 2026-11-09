#!/usr/bin/env python3
"""
OPS-39 (#232): close crawl_log rows that no run will ever close -- 'started' rows
older than their job's Task Scheduler time limit (newscrawler/tools/crawl_log_orphans.py:
8 h for the knowledge extraction, 4 h for everything else). Such a run was killed or
crashed; the row still answers "is a run going?" with yes.

A dry run is the default and writes nothing. --apply writes the rows as they are
(log_id, website, task, started_at, status, finished_at, error_msg) to
backups/ops39_crawl_log_<timestamp>.json first, then sets status = 'failed',
finished_at = started_at and error_msg = 'abandoned: no run owned this row (closed
<date>)', and re-counts (exit 1 if any are left). --restore <that file> undoes it.

Usage:
    python scripts/close_abandoned_crawl_log.py                 # dry run
    python scripts/close_abandoned_crawl_log.py --apply
    python scripts/close_abandoned_crawl_log.py --restore backups/ops39_crawl_log_20261006_2130.json
"""
import argparse
import json
import os
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
from newscrawler.tools import crawl_log_orphans  # noqa: E402

_COLUMNS = "log_id, website, task, started_at, status, finished_at, error_msg"


def _backup_rows(session, ids):
    rows = session.execute(text(f"SELECT {_COLUMNS} FROM crawl_log WHERE log_id = ANY(:ids) ORDER BY log_id"),
                           {"ids": ids}).fetchall()
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row._mapping.items()} for row in rows]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="back up, then close (default: dry run)")
    mode.add_argument("--restore", metavar="BACKUP", help="put an --apply backup's rows back as they were")
    parser.add_argument("--backup-dir", default=os.path.join(ROOT, "backups"))
    args = parser.parse_args(argv)
    client = SQLAlchemyClient()

    if args.restore:
        with open(args.restore, encoding="utf-8") as f:
            rows = json.load(f)
        with client.get_session() as session:
            for row in rows:
                session.execute(text("UPDATE crawl_log SET status = :status, finished_at = :finished_at, "
                                     "error_msg = :error_msg WHERE log_id = :log_id"), row)
            session.commit()
        print(f"Restored {len(rows)} crawl_log row(s) from {args.restore}.")
        return 0

    with client.get_session() as session:
        orphans = crawl_log_orphans.find_orphans(session)
        print(f"{len(orphans)} crawl_log row(s) 'started' past their job's time limit"
              + (f": {crawl_log_orphans.describe(orphans, limit=len(orphans))}" if orphans else ""))
        if not args.apply or not orphans:
            if not args.apply:
                print("[dry-run] nothing written; --apply to back up and close.")
            return 0
        os.makedirs(args.backup_dir, exist_ok=True)
        backup = os.path.join(args.backup_dir, f"ops39_crawl_log_{datetime.now():%Y%m%d_%H%M%S}.json")
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(_backup_rows(session, [r.log_id for r in orphans]), f, indent=1)
        closed = crawl_log_orphans.close_orphans(
            session, orphans, f"abandoned: no run owned this row (closed {date.today().isoformat()}, OPS-39)")
        left = len(crawl_log_orphans.find_orphans(session))
    print(f"Closed {closed} row(s); backup {backup}; orphans left: {left}.")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
