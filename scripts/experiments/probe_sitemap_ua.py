#!/usr/bin/env python3
"""
Probe every sitemap URL in the URL enum with (a) the project's default User-Agent and
(b) a modern browser UA, and print status code / size / content-type side by side.

Use it to tell bot-blocking apart from dead URLs or format changes before touching a
crawler: if both columns agree, the UA is not the problem.

Usage (from repo root):
    venv\Scripts\python.exe scripts/experiments/probe_sitemap_ua.py
    venv\Scripts\python.exe scripts/experiments/probe_sitemap_ua.py --only BISNIS,IDNTIMES

First run + conclusions: EXPERIMENTS.md, entry 2026-09-15 "User-Agent is not why sitemaps fail".
"""
import argparse
import concurrent.futures as cf
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader  # noqa: E402
from newscrawler.domain.entities.extraction.url_data import URL  # noqa: E402

MODERN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def probe(name, url, header_sets):
    row = [name, url[:55]]
    for hdr in header_sets:
        try:
            r = requests.get(url, headers=hdr, timeout=(10, 20), allow_redirects=True)
            row.append(f"{r.status_code} {len(r.content) // 1024}KB {r.headers.get('content-type', '')[:20]}")
        except Exception as e:
            row.append(f"EXC {type(e).__name__}")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated WebsiteName values to probe")
    args = ap.parse_args()

    default = RequestsPageLoader().headers
    modern = dict(default, **{"User-Agent": MODERN_UA})
    targets = [(m.name, m.value) for m in URL if m.value]
    if args.only:
        wanted = {w.strip().upper() for w in args.only.split(",")}
        targets = [t for t in targets if t[0] in wanted]

    with cf.ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(lambda t: probe(t[0], t[1], (default, modern)), targets))

    print(f"{'SOURCE':14} {'URL':56} {'DEFAULT-UA':28} MODERN-UA")
    for r in sorted(rows):
        print(f"{r[0]:14} {r[1]:56} {r[2]:28} {r[3]}")
    differs = [r[0] for r in rows if r[2].split()[0] != r[3].split()[0]]
    print(f"\nUA changes the status code for: {', '.join(differs) if differs else 'none'}")


if __name__ == "__main__":
    main()
