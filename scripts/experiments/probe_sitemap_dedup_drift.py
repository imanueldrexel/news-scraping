#!/usr/bin/env python3
"""
SYS-29 (#84) probe: how many rows would the next `task=sitemap` insert as
duplicates of links that are already stored?

`save_sitemaps` dedups on `(link, int(posted_at))` in a Python-side map with no
unique index behind it. Anything that changes the derived `posted_at` for a link
a site still lists -- SYS-11's WIB fix (+1 day for 00:00-06:59 WIB articles), or a
site re-stamping `news:publication_date` -- therefore inserts a second `sitemaps`
row, which has no `articles` row, re-enters the crawl queue, and produces a second
`articles` row plus duplicate chunks/FAISS vectors for the same URL.

Read-only: fetches each source's live sitemap through the real crawler (network),
computes today's `(link, posted_at)` per entry, and compares against the stored rows
for those links. Writes nothing. Run before and after a dedup-key change; SYS-29's
Done-when is 0 `would_insert_duplicate` for every HEALTHY source.

Usage:
    python scripts/experiments/probe_sitemap_dedup_drift.py                # __main__.HEALTHY
    python scripts/experiments/probe_sitemap_dedup_drift.py CNBC KOMPAS    # subset

2026-09-18 baseline (before the SYS-29 fix): 4,024 would-insert duplicates across
the 21 HEALTHY sources -- 3,817 exactly the SYS-11 +1-day shift (VIVA 2,511,
JPNN 816, TVONENEWS 161, PIKIRANRAKYAT 150, IDXCHANNEL 83, TRIBUN 35,
WARTAEKONOMI 26, CNBC 19, GRIDID 12, SINDONEWS 4), 207 other re-stamps
(OKEZONE 206, GRIDID 1).
"""
import logging
import os
import sys
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_ROOT, ".env"))

logging.disable(logging.WARNING)

from sqlalchemy import text

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _day(i: int) -> datetime:
    return datetime.strptime(str(i), "%Y%m%d")


def probe(site: str, client: SQLAlchemyClient) -> dict:
    crawler = CRAWLER_DICT[site]
    dtos = crawler.batch_crawling_sitemap(crawler.get_news_in_bulk(), site)
    dtos = [d for d in dtos if d and d.link and d.timestamp]
    new_key = {d.link: int(d.timestamp.strftime("%Y%m%d")) for d in dtos}
    if not new_key:
        return {"site": site, "listed": 0}
    with client.get_session() as s:
        rows = s.execute(
            text("SELECT link, posted_at FROM sitemaps WHERE sources = :src AND link = ANY(:links)"),
            {"src": site, "links": list(new_key)},
        ).fetchall()
    stored = {}
    for link, posted_at in rows:
        stored.setdefault(link, set()).add(posted_at)
    dup = [(l, stored[l], new_key[l]) for l in new_key if l in stored and new_key[l] not in stored[l]]
    plus_one = sum(1 for _, old, new in dup if any(_day(new) - _day(o) == timedelta(days=1) for o in old))
    return {
        "site": site, "listed": len(new_key), "already_in_db": len(stored),
        "same_key": sum(1 for l in new_key if l in stored and new_key[l] in stored[l]),
        "would_insert_duplicate": len(dup), "sys11_plus_one_day": plus_one,
        "other_restamp": len(dup) - plus_one, "genuinely_new": sum(1 for l in new_key if l not in stored),
        "examples": [(l[:90], sorted(old), new) for l, old, new in dup[:3]],
    }


def main() -> int:
    if len(sys.argv) > 1:
        sites = [s.upper() for s in sys.argv[1:]]
    else:
        # The repo's __main__.py holds the HEALTHY list; load it by path (importing
        # "__main__" from inside a script would just return this script).
        import importlib.util
        spec = importlib.util.spec_from_file_location("repo_entry", os.path.join(REPO_ROOT, "__main__.py"))
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        sites = list(entry.HEALTHY)
    client = SQLAlchemyClient()
    total_dup = total_plus_one = 0
    for site in sites:
        try:
            r = probe(site, client)
        except Exception as e:  # a broken source is not this probe's concern
            print(f"{site}: ERROR {type(e).__name__}: {str(e)[:120]}")
            continue
        if r["listed"] == 0:
            print(f"{site}: sitemap returned 0 entries")
            continue
        print(f"{site}: listed={r['listed']} already_in_db={r['already_in_db']} same_key={r['same_key']} "
              f"would_insert_duplicate={r['would_insert_duplicate']} "
              f"[sys11_plus_one_day={r['sys11_plus_one_day']} other_restamp={r['other_restamp']}] "
              f"genuinely_new={r['genuinely_new']}")
        for link, old, new in r["examples"]:
            print(f"    {link}  stored={old} -> new={new}")
        total_dup += r["would_insert_duplicate"]
        total_plus_one += r["sys11_plus_one_day"]
    print(f"\nTOTAL would_insert_duplicate={total_dup} (sys11_plus_one_day={total_plus_one})")
    return 1 if total_dup else 0


if __name__ == "__main__":
    sys.exit(main())
