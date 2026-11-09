#!/usr/bin/env python3
"""
SRC-02..06: re-diagnose every BROKEN/ERROR outlet from the daily health check,
live, in one pass -- so the tickets describe today's failure, not 2026-09-15's.

Per outlet:
  1. the configured URL enum entry through the real RequestsPageLoader
     (get_soup_with_reason -> the OPS-15 reason: "HTTP 404", "ConnectionError
     after N retries", "soft-404: ...") plus a raw requests.get for status /
     final URL / content-type / size;
  2. https://<host>/robots.txt -> every `Sitemap:` line;
  3. each candidate sitemap (robots + a short list of conventional paths):
     status, whether it is an index (<sitemap>) or a leaf (<url>), entry count,
     and the first few <loc>s -- enough to tell "dead", "moved", "blocked",
     "format changed" apart without opening a browser.

Read-only, network only. ~1-2 min for the default 11 outlets.

Usage:
    python scripts/experiments/probe_broken_sources.py                    # today's BROKEN/ERROR set
    python scripts/experiments/probe_broken_sources.py TEMPO LIPUTAN6     # subset
    python scripts/experiments/probe_broken_sources.py --all              # every URL enum entry

2026-09-19 first run: EXPERIMENTS.md "2026-09-19 -- SRC-02..06: what is actually
wrong with the 11 BROKEN/ERROR outlets today".
"""
import argparse
import os
import re
import sys
import time
from urllib.parse import urlparse, urljoin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

import requests
from bs4 import BeautifulSoup

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.entities.extraction.url_data import URL

# The 2026-09-19 health-check BROKEN/ERROR set (SRC-02 x5, SRC-03 x2, SRC-04, SRC-05, SRC-06 x2).
# All fixed by 2026-09-20 except BISNIS (SRC-03, genuine Cloudflare challenge).
# BATAMPOS and KAPANLAGI were retired (SRC-17/SRC-18) rather than fixed --
# removed from URL/WebsiteName entirely, so they'd KeyError here now.
DEFAULT = ["ANTARANEWS", "TIRTO", "SUARA",
           "BISNIS", "IDNTIMES", "INEWS", "LIPUTAN6", "MERDEKA", "TEMPO"]

# Known/likely homes for the sources whose enum entry is empty or off-site.
HOME = {
    "SUARA": "https://www.suara.com/",
    "ANTARANEWS": "https://www.antaranews.com/",
}

CONVENTIONAL = ["sitemap.xml", "sitemap_news.xml", "sitemap-news.xml", "news-sitemap.xml",
                "sitemap/news.xml", "sitemap/sitemap-news.xml", "sitemap_index.xml", "sitemap/index.xml"]

HEADERS = RequestsPageLoader().headers
TIMEOUT = (10, 20)


def fetch(url, verify=True):
    """(status, final_url, content_type, bytes, text_or_None, error)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, verify=verify)
        ct = r.headers.get("content-type", "")
        return r.status_code, r.url, ct, len(r.content), r.text, None
    except Exception as e:
        return None, None, None, 0, None, f"{type(e).__name__}: {str(e)[:120]}"


def classify_xml(text):
    """('index'|'leaf'|'html'|'other', count, [first locs])"""
    if text is None:
        return "none", 0, []
    head = text.lstrip()[:300].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return "html", 0, []
    soup = BeautifulSoup(text, "xml")
    sitemaps = soup.find_all("sitemap")
    if sitemaps:
        locs = [s.find("loc").text.strip() for s in sitemaps if s.find("loc")]
        return "index", len(sitemaps), locs[:6]
    urls = soup.find_all("url")
    if urls:
        locs = [u.find("loc").text.strip() for u in urls if u.find("loc")]
        return "leaf", len(urls), locs[:3]
    items = soup.find_all("item")
    if items:
        return "rss", len(items), [i.find("link").text.strip() for i in items[:3] if i.find("link")]
    return "other", 0, []


def robots_sitemaps(base):
    st, _, _, _, text, err = fetch(urljoin(base, "/robots.txt"))
    if text is None or st != 200:
        return [], f"robots.txt -> {st or err}"
    lines = [l.split(":", 1)[1].strip() for l in text.splitlines() if l.lower().startswith("sitemap:")]
    return lines, f"robots.txt -> 200, {len(lines)} Sitemap line(s)"


def probe(name, configured):
    print(f"\n{'=' * 78}\n{name}   configured: {configured or '(empty)'}")
    base = configured or HOME.get(name, "")
    if not base:
        print("  no URL and no known home -- nothing to probe")
        return
    host_base = f"{urlparse(base).scheme}://{urlparse(base).netloc}/"

    # 1. configured URL, exactly as the pipeline sees it
    if configured:
        t = time.perf_counter()
        soup, reason = RequestsPageLoader().get_soup_with_reason(configured)
        print(f"  pipeline loader: {'soup OK' if soup else 'None'}  reason={reason!r}  ({time.perf_counter() - t:.1f}s)")
        st, final, ct, n, text, err = fetch(configured)
        kind, cnt, locs = classify_xml(text)
        print(f"  raw GET: status={st} final={final!r} type={ct!r} bytes={n} {('ERR ' + err) if err else ''}")
        print(f"           body={kind} entries={cnt} {locs[:3]}")
        if err and "SSL" in err:
            st2, final2, ct2, n2, text2, err2 = fetch(configured, verify=False)
            kind2, cnt2, locs2 = classify_xml(text2)
            print(f"  verify=False: status={st2} type={ct2!r} bytes={n2} body={kind2} entries={cnt2} {locs2[:3]} {('ERR ' + err2) if err2 else ''}")

    # 2. robots.txt
    lines, note = robots_sitemaps(host_base)
    print(f"  {note}")
    candidates = []
    for l in lines:
        if l not in candidates:
            candidates.append(l)
    for p in CONVENTIONAL:
        u = urljoin(host_base, p)
        if u not in candidates and u != configured:
            candidates.append(u)

    # 3. candidates
    print("  candidates:")
    for u in candidates[:14]:
        st, final, ct, n, text, err = fetch(u)
        if err:
            print(f"    {u[:70]:<70} ERR {err}")
            continue
        kind, cnt, locs = classify_xml(text if st == 200 else None)
        moved = f" -> {final[:50]}" if final and final.rstrip('/') != u.rstrip('/') else ""
        print(f"    {u[:70]:<70} {st}{moved}  {kind:<5} n={cnt:<4} {n // 1024}KB")
        for loc in locs[:4]:
            print(f"        {loc[:100]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="outlet names (URL enum); default = today's BROKEN/ERROR set")
    ap.add_argument("--all", action="store_true", help="every URL enum entry")
    args = ap.parse_args(argv)
    names = [u.name for u in URL] if args.all else (args.names or DEFAULT)
    for name in names:
        try:
            probe(name, URL[name].value)
        except KeyError:
            print(f"\n{name}: not in URL enum")
    return 0


if __name__ == "__main__":
    sys.exit(main())
