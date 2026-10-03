#!/usr/bin/env python3
"""Would a real `task=sitemap` list anything the scope decision says it must not?

Read-only end-to-end check of the listing path: for each registered crawler it
runs the SHIPPED `get_news_in_bulk()` -- the same `_get_branches` ->
`drop_soft_branches` -> `_scrape` chain a real run uses -- and inspects the URLs
that would have been inserted, without touching the database.

This exists because the branch-level scope rules (SRC-35 #128, SRC-43 #146,
SRC-45 #155, SYS-49 #147) are enforced on the branch KEY, while what actually
reaches `sitemaps` is a URL. Unit tests pin the key logic; `probe_branch_scope.py`
pins the key SET; neither answers "did a URL from a dropped section still get
listed". That question needs the real listing path, and it is the one OPS-19
(#132) has to be able to answer before it schedules anything.

Two independent checks, because they fail differently:

  1. BRANCH ATTRIBUTION -- `_scrape` stamps each entry's `category` with the
     branch it came from, so any listed entry whose category is a dropped key is
     a leak in `drop_soft_branches`.
  2. URL SHAPE -- every listed link is matched against the soft vocabulary and
     the archive shape on its host and path. This catches what check 1 cannot:
     a soft section reached through a branch that is itself kept (the
     MEDIAINDONESIA `_get_branch_name_from_url` shape), or a crawler whose
     category stamp does not match the branch it fetched.

Exit 0 when nothing leaks, 1 when something does, 2 on a fetch failure.

    venv\\Scripts\\python.exe scripts/experiments/verify_branch_scope_live.py --website OKEZONE,IDXCHANNEL
    venv\\Scripts\\python.exe scripts/experiments/verify_branch_scope_live.py          # every registered crawler
"""
import argparse
import collections
import json
import os
import re
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.crawler import SOFT_BRANCH_WORDS, Crawler  # noqa: E402


from newscrawler.infrastructure.datasource.scrapers.crawler import SitemapIndexUnavailable  # noqa: E402

def url_segments(link: str):
    """The SECTION-like parts of a URL: host labels plus the path segments that
    could name a desk.

    Deliberately excludes the final path segment and any purely numeric one.
    The last segment is the article slug, and a slug is prose -- it contains
    `bola`, `korea`, `video` and `foto` for reasons that have nothing to do
    with the section it sits in. Matching the vocabulary against it reported
    512 false leaks on the first run of this script, including
    `...-podcast-bola-mnc-university` (an education desk article) and
    `...-berapa-liter-air-untuk-satu-foto-ai` (a tech desk article). A segment
    that is all digits is an article id or a date component, never a section;
    `2015-02` is kept, because that IS the archive shape."""
    parsed = urlparse(link or "")
    host = [h for h in parsed.netloc.lower().split(".") if h not in ("www", "com", "co", "id", "net", "org")]
    path = [p for p in parsed.path.lower().split("/") if p]
    sections = [p for p in path[:-1] if not p.isdigit() and len(p) <= 20]
    return host + sections


def url_is_soft(crawler, link: str):
    """The first segment of the URL that the shipped predicate calls soft, or
    None. Uses `crawler.is_soft_branch` so per-crawler SOFT_BRANCH_EXCEPTIONS
    are honoured -- IDXCHANNEL `foto` is a kept desk and must not be reported."""
    for segment in url_segments(link):
        if crawler.is_soft_branch(segment) or crawler.is_archive_branch(segment):
            return segment
    return None


def check(name, crawler, verbose=False):
    result = {"website": name, "status": "OK", "listed": 0, "branches": 0, "kept": 0,
              "dropped_soft": [], "dropped_archive": [], "leaks_by_category": {}, "leaks_by_url": {}}
    branches = crawler.list_branches()  # every index (SRC-38)
    if branches is None:
        result["status"] = "NO_INDEX"
        return result
    kept = crawler.drop_soft_branches(branches)
    result["branches"] = len(branches)
    result["kept"] = len(kept)
    result["dropped_soft"] = sorted(k for k in branches if crawler.is_soft_branch(k))
    result["dropped_archive"] = sorted(
        k for k in branches if not crawler.is_soft_branch(k) and crawler.is_archive_branch(k))

    try:
        listed = crawler.get_news_in_bulk() or []
    except SitemapIndexUnavailable as e:  # OPS-35: raised, no longer []
        print(f"{name}: {e}")
        listed = []
    result["listed"] = len(listed)

    dropped = set(result["dropped_soft"]) | set(result["dropped_archive"])
    by_category = collections.Counter()
    by_url = collections.Counter()
    samples = {}
    for entry in listed:
        category = (entry.get("category") or "").strip()
        if category in dropped:
            by_category[category] += 1
            samples.setdefault("cat:" + category, entry.get("link"))
        segment = url_is_soft(crawler, entry.get("link"))
        if segment:
            by_url[segment] += 1
            samples.setdefault("url:" + segment, entry.get("link"))
    result["leaks_by_category"] = dict(by_category)
    result["leaks_by_url"] = dict(by_url)
    result["samples"] = samples
    if by_category or by_url:
        result["status"] = "LEAK"
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", default=None, help="Comma-separated crawler names (default: all registered)")
    ap.add_argument("--json-out", default=None, help="Write the full result to this path")
    args = ap.parse_args(argv)

    names = [w.strip().upper() for w in args.website.split(",")] if args.website else sorted(CRAWLER_DICT)
    results, failed = [], False
    for name in names:
        if name not in CRAWLER_DICT:
            print(f"{name}: not registered")
            return 2
        try:
            r = check(name, CRAWLER_DICT[name])
        except Exception as e:  # noqa: BLE001 -- report, don't die mid-fleet
            r = {"website": name, "status": f"ERROR {type(e).__name__}: {str(e)[:80]}",
                 "listed": 0, "branches": 0, "kept": 0, "dropped_soft": [], "dropped_archive": [],
                 "leaks_by_category": {}, "leaks_by_url": {}, "samples": {}}
        results.append(r)
        print(f"{r['website']:16} {r['status']:8} branches={r['branches']:4d} kept={r['kept']:4d} "
              f"soft={len(r['dropped_soft']):3d} archive={len(r['dropped_archive']):4d} "
              f"listed_urls={r['listed']:6d}")
        if r["leaks_by_category"]:
            print(f"{'':16} LEAK by branch : {r['leaks_by_category']}")
        if r["leaks_by_url"]:
            print(f"{'':16} LEAK by url    : {r['leaks_by_url']}")
        for k, v in (r.get("samples") or {}).items():
            print(f"{'':16}   {k} -> {v}")
        if r["status"] != "OK":
            failed = True

    total = sum(r["listed"] for r in results)
    leaks = sum(sum(r["leaks_by_category"].values()) + sum(r["leaks_by_url"].values()) for r in results)
    print(f"\n{len(results)} source(s): {total} URL(s) would be listed, {leaks} of them from a dropped section")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
        print(f"wrote {args.json_out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
