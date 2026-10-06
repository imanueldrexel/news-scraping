#!/usr/bin/env python3
"""
SYS-90 (#255): put the right day back into articles.meta_data.posted_at where the
pydantic-2 int-as-Unix-seconds coercion wrote 1970 (193 CNBC articles, from a
script that built SitemapDTOs from stored rows on 2026-09-22: posted_at 19700823).

The right value is the article's own sitemaps.posted_at (int yyyymmdd), which was
never touched. Only rows whose meta_data.posted_at is a number below 20000101 are
changed; nothing else in meta_data is.

A dry run is the default and writes nothing. --apply writes (sitemap_id, old, new)
to backups/sys90_posted_at_<timestamp>.json first, updates in one transaction and
re-counts (exit 1 if any are left). --restore <that file> undoes it.

Usage:
    python scripts/repair_article_posted_at.py              # dry run
    python scripts/repair_article_posted_at.py --apply
    python scripts/repair_article_posted_at.py --restore backups/sys90_posted_at_20261006_2200.json
"""
import argparse
import collections
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

BROKEN_SQL = text(
    "SELECT a.sitemap_id, s.sources, a.meta_data->>'posted_at' AS old, s.posted_at AS new "
    "FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id "
    "WHERE (a.meta_data->>'posted_at') ~ '^[0-9]+$' AND (a.meta_data->>'posted_at')::bigint < 20000101 "
    "ORDER BY a.sitemap_id")
SET_SQL = text("UPDATE articles SET meta_data = jsonb_set(meta_data::jsonb, '{posted_at}', to_jsonb(CAST(:value AS int)))"
               " WHERE sitemap_id = :sitemap_id")


def broken(session):
    return [dict(r._mapping) for r in session.execute(BROKEN_SQL).fetchall()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="back up, then repair (default: dry run)")
    mode.add_argument("--restore", metavar="BACKUP", help="put an --apply backup's old values back")
    parser.add_argument("--backup-dir", default=os.path.join(ROOT, "backups"))
    args = parser.parse_args(argv)
    client = SQLAlchemyClient()

    if args.restore:
        with open(args.restore, encoding="utf-8") as f:
            rows = json.load(f)
        with client.get_session() as session:
            for r in rows:
                session.execute(SET_SQL, {"value": int(r["old"]), "sitemap_id": r["sitemap_id"]})
            session.commit()
        print(f"Restored {len(rows)} article(s) from {args.restore}.")
        return 0

    with client.get_session() as session:
        rows = broken(session)
        per_source = collections.Counter(r["sources"] for r in rows)
        print(f"{len(rows)} article(s) with a pre-2000 meta_data.posted_at -- "
              + (", ".join(f"{s}: {n}" for s, n in per_source.most_common()) or "none"))
        for r in rows[:5]:
            print(f"  sitemap {r['sitemap_id']} {r['sources']}: {r['old']} -> {r['new']}")
        if not args.apply or not rows:
            if not args.apply:
                print("[dry-run] nothing written; --apply to back up and repair.")
            return 0
        os.makedirs(args.backup_dir, exist_ok=True)
        backup = os.path.join(args.backup_dir, f"sys90_posted_at_{datetime.now():%Y%m%d_%H%M%S}.json")
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=0)
        for r in rows:
            session.execute(SET_SQL, {"value": int(r["new"]), "sitemap_id": r["sitemap_id"]})
        session.commit()
        left = len(broken(session))
    print(f"Repaired {len(rows)} article(s); backup {backup}; left: {left}.")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
