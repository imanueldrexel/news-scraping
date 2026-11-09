#!/usr/bin/env python3
"""
Sample article URLs from a source's sitemap and report which ones are "soft 404s":
the server redirects (or answers directly) with HTTP 200 but the final URL / page is
an error or home page, not the article. `RequestsPageLoader.get_soup` only checks
`status_code == 200`, so these pages flow into the extractor chain and trafilatura
happily returns the home page's boilerplate as the article body (SYS-14).

For every sampled URL it prints: sitemap date, final status, redirect chain, whether
the final path looks like an error page, whether the site selector found its
container, and how many chars trafilatura would extract.

Usage (from repo root):
    venv\Scripts\python.exe scripts/experiments/probe_soft404.py --website EMITENNEWS
    venv\Scripts\python.exe scripts/experiments/probe_soft404.py --website KOMPAS --sample 30 --seed 1

First run + conclusions: EXPERIMENTS.md, entry 2026-09-16
"EMITENNEWS serves its home page with HTTP 200 for missing articles (SRC-01 re-audit)".
"""
import argparse
import os
import random
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402

ERROR_PATH = re.compile(r"/(404|not-?found|error)(/|$|\?)", re.I)


def probe(crawler, entry):
    url = entry["link"]
    try:
        r = requests.get(url, headers=crawler.page_loader.headers, timeout=(10, 27), allow_redirects=True)
    except Exception as e:
        return {"url": url, "verdict": "EXC", "detail": type(e).__name__}
    soup = BeautifulSoup(r.content, "html.parser")
    try:
        site = crawler._get_whole_text(soup)
    except Exception as e:
        site = f"RAISED {type(e).__name__}"
    site_len = crawler._text_length(site) if not isinstance(site, str) or not site.startswith("RAISED") else -1
    traf_len = crawler._text_length(crawler._trafilatura_fallback(soup))
    final_path = requests.utils.urlparse(r.url).path
    soft404 = r.status_code == 200 and bool(ERROR_PATH.search(final_path))
    return {
        "url": url,
        "date": entry["timestamp"].date().isoformat() if entry.get("timestamp") else "-",
        "status": r.status_code,
        "chain": "->".join(str(h.status_code) for h in r.history) or "-",
        "final": final_path[:40],
        "site_len": site_len,
        "traf_len": traf_len,
        "verdict": "SOFT404" if soft404 else ("ok" if r.status_code == 200 else f"HTTP{r.status_code}"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--website", required=True, help="WebsiteName value, e.g. EMITENNEWS")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    crawler = CRAWLER_DICT.get(args.website.upper())
    if crawler is None:
        sys.exit(f"unknown website {args.website}")
    entries = crawler.get_news_in_bulk()
    print(f"{args.website}: {len(entries)} sitemap entries")
    if not entries:
        return 1
    random.seed(args.seed)
    sample = random.sample(entries, min(args.sample, len(entries)))

    rows = [probe(crawler, e) for e in sample]
    print(f"{'DATE':10} {'VERDICT':8} {'ST':4} {'CHAIN':8} {'FINAL PATH':40} {'SITE':>6} {'TRAF':>6}  URL")
    for r in sorted(rows, key=lambda x: (x.get("verdict"), x.get("date", ""))):
        if r["verdict"] == "EXC":
            print(f"{'-':10} {'EXC':8} {r['detail']:60} {r['url'][:60]}")
            continue
        print(f"{r['date']:10} {r['verdict']:8} {r['status']:<4} {r['chain']:8} {r['final']:40} "
              f"{r['site_len']:>6} {r['traf_len']:>6}  {r['url'][:70]}")
    n_soft = sum(1 for r in rows if r["verdict"] == "SOFT404")
    print(f"\nsoft-404: {n_soft}/{len(rows)}   "
          f"(these pass get_soup, and any with TRAF >= MIN_ARTICLE_CHARS are saved as article text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
