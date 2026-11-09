#!/usr/bin/env python3
"""
SYS-29 (#84) probe: how many rows would the next `task=sitemap` insert for links
that are already stored?

Before SYS-29, `save_sitemaps` dedupped on `(link, int(posted_at))` in a
Python-side map with no unique index behind it. Anything that changed the derived
`posted_at` for a link a site still lists -- SYS-11's WIB fix (+1 day for
00:00-06:59 WIB articles), or a site re-stamping `news:publication_date` --
therefore inserted a second `sitemaps` row, which had no `articles` row,
re-entered the crawl queue, and produced a second `articles` row plus duplicate
chunks/FAISS vectors for the same URL.

Read-only: fetches each source's live sitemap through the real crawler (network),
then asks the REAL dedup lookup (`SQLAlchemySitemapDataSource.find_existing_by_link`)
which of those links it would treat as already stored -- so this probe cannot
drift from the code the way its first version did (it re-derived the old
`(link, posted_at)` key by hand). `would_insert_duplicate` is a stored link the
lookup does not recognise; `date_drift` is informational only (stored links whose
posted_at differs from today's derivation -- the population SYS-29 protects).
Writes nothing. Exit 1 while any source would duplicate.

Usage:
    python scripts/experiments/probe_sitemap_dedup_drift.py                # __main__.HEALTHY
    python scripts/experiments/probe_sitemap_dedup_drift.py CNBC KOMPAS    # subset

2026-09-18 baseline (before the SYS-29 fix, old key): 4,024 would-insert
duplicates across the 21 HEALTHY sources -- 3,817 exactly the SYS-11 +1-day shift
(VIVA 2,511, JPNN 816, TVONENEWS 161, PIKIRANRAKYAT 150, IDXCHANNEL 83, TRIBUN 35,
WARTAEKONOMI 26, CNBC 19, GRIDID 12, SINDONEWS 4), 207 other re-stamps
(OKEZONE 206, GRIDID 1). Those 4,024 now show up under `date_drift`, not
`would_insert_duplicate`.
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
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _day(i: int) -> datetime:
    return datetime.strptime(str(i), "%Y%m%d")


def probe(site: str, datasource: SQLAlchemySitemapDataSource) -> dict:
    crawler = CRAWLER_DICT[site]
    dtos = crawler.batch_crawling_sitemap(crawler.get_news_in_bulk(), site)
    dtos = [d for d in dtos if d and d.link and d.timestamp]
    new_key = {d.link: int(d.timestamp.strftime("%Y%m%d")) for d in dtos}
    if not new_key:
        return {"site": site, "listed": 0}

    # What the real code would dedup against.
    recognised = datasource.find_existing_by_link(new_key)

    # What is actually stored for these links (any source), for the informational
    # date-drift count and to catch a link stored but not recognised.
    with datasource.client.get_session() as s:
        rows = s.execute(
            text("SELECT link, posted_at FROM sitemaps WHERE link = ANY(:links)"),
            {"links": list(new_key)},
        ).fetchall()
    stored = {}
    for link, posted_at in rows:
        stored.setdefault(link, set()).add(posted_at)

    would_insert_dup = [l for l in new_key if l in stored and l not in recognised]
    drift = [(l, stored[l], new_key[l]) for l in new_key if l in stored and new_key[l] not in stored[l]]
    plus_one = sum(1 for _, old, new in drift if any(_day(new) - _day(o) == timedelta(days=1) for o in old))
    return {
        "site": site, "listed": len(new_key), "already_in_db": len(stored),
        "recognised": sum(1 for l in new_key if l in recognised),
        "would_insert_duplicate": len(would_insert_dup),
        "date_drift": len(drift), "sys11_plus_one_day": plus_one, "other_restamp": len(drift) - plus_one,
        "genuinely_new": sum(1 for l in new_key if l not in stored),
        "examples": [(l[:90], sorted(old), new) for l, old, new in drift[:3]],
        "dup_examples": [l[:90] for l in would_insert_dup[:3]],
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
    datasource = SQLAlchemySitemapDataSource(SQLAlchemyClient())
    total_dup = total_drift = total_plus_one = 0
    for site in sites:
        try:
            r = probe(site, datasource)
        except Exception as e:  # a broken source is not this probe's concern
            print(f"{site}: ERROR {type(e).__name__}: {str(e)[:120]}")
            continue
        if r["listed"] == 0:
            print(f"{site}: sitemap returned 0 entries")
            continue
        print(f"{site}: listed={r['listed']} already_in_db={r['already_in_db']} recognised={r['recognised']} "
              f"would_insert_duplicate={r['would_insert_duplicate']} "
              f"date_drift={r['date_drift']} [sys11_plus_one_day={r['sys11_plus_one_day']} "
              f"other_restamp={r['other_restamp']}] genuinely_new={r['genuinely_new']}")
        for link in r["dup_examples"]:
            print(f"    WOULD DUPLICATE: {link}")
        for link, old, new in r["examples"]:
            print(f"    drift: {link}  stored={old} -> today={new}")
        total_dup += r["would_insert_duplicate"]
        total_drift += r["date_drift"]
        total_plus_one += r["sys11_plus_one_day"]
    print(f"\nTOTAL would_insert_duplicate={total_dup} date_drift={total_drift} (sys11_plus_one_day={total_plus_one})")
    return 1 if total_dup else 0


if __name__ == "__main__":
    sys.exit(main())
