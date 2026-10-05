#!/usr/bin/env python3
"""
SYS-88 (#249): unescape the HTML entities in headlines stored before the fix
("Jatim &amp;amp; Kalsel" -> "Jatim & Kalsel"). New rows are unescaped at
ingest (Crawler._get_sitemap, Crawler._get_page_title), and the newsletter reads
old rows through the same function, so this only makes the stored rows agree
with what every reader already sees.

Reads every sitemaps row whose headline holds an entity, computes
`unescape_headline(headline)`, and reports the rows that would change, per
source. A dry run is the default and writes nothing.

--apply first writes every changed row's old headline to
backups/sys88_headlines_<timestamp>.json (sitemap_id, old, new), then updates
them in one transaction. Undo: --restore <that file>.

Usage:
    python scripts/unescape_stored_headlines.py                    # dry run
    python scripts/unescape_stored_headlines.py --apply
    python scripts/unescape_stored_headlines.py --restore backups/sys88_headlines_20261005_2300.json
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

from newscrawler.core.utils.utils import unescape_headline  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

# Any named or numeric entity. The rows are then decided in Python: a headline
# that unescapes to itself is left alone.
ENTITY_SQL = r"headline ~ '&(#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z]+);'"


def changes(session) -> list:
    rows = session.execute(text(f"SELECT sitemap_id, sources, headline FROM sitemaps WHERE {ENTITY_SQL} "
                                f"ORDER BY sitemap_id")).fetchall()
    out = []
    for row in rows:
        new = unescape_headline(row.headline)
        if new != row.headline:
            out.append({"sitemap_id": row.sitemap_id, "source": row.sources, "old": row.headline, "new": new})
    return out


def _update(session, pairs) -> None:
    for sitemap_id, headline in pairs:
        session.execute(text("UPDATE sitemaps SET headline = :headline WHERE sitemap_id = :sitemap_id"),
                        {"headline": headline, "sitemap_id": sitemap_id})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="back up, then write (default: dry run)")
    mode.add_argument("--restore", metavar="BACKUP", help="put the old headlines of an --apply backup back")
    parser.add_argument("--backup-dir", default=os.path.join(ROOT, "backups"))
    args = parser.parse_args(argv)
    client = SQLAlchemyClient()

    if args.restore:
        with open(args.restore, encoding="utf-8") as f:
            rows = json.load(f)
        with client.get_session() as session:
            _update(session, [(r["sitemap_id"], r["old"]) for r in rows])
            session.commit()
        print(f"Restored {len(rows)} headline(s) from {args.restore}.")
        return 0

    with client.get_session() as session:
        found = changes(session)
        per_source = collections.Counter(r["source"] for r in found)
        print(f"{len(found)} headline(s) to unescape -- "
              + (", ".join(f"{s}: {n}" for s, n in per_source.most_common()) or "none"))
        for r in found[:10]:
            print(f"  {r['sitemap_id']} {r['source']}: {r['old']!r} -> {r['new']!r}")
        if not args.apply or not found:
            if not args.apply:
                print("[dry-run] nothing written; --apply to back up and write.")
            return 0
        os.makedirs(args.backup_dir, exist_ok=True)
        backup = os.path.join(args.backup_dir, f"sys88_headlines_{datetime.now():%Y%m%d_%H%M%S}.json")
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(found, f, ensure_ascii=False, indent=0)
        _update(session, [(r["sitemap_id"], r["new"]) for r in found])
        session.commit()
        left = len(changes(session))
    print(f"Unescaped {len(found)} headline(s); backup {backup}; rows still to change: {left}.")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
