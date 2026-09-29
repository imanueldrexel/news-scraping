#!/usr/bin/env python3
"""
DBT-05 (#24): should article extraction be selector-first or layout-independent
first? For a few recent saved articles per source, fetch the page once and run
three extractors on it:

  site  -- the crawler's own `_get_whole_text` (the hand-written selectors)
  jsonld -- `articleBody` of a NewsArticle/Article object in
            <script type="application/ld+json"> (layout-independent)
  traf  -- trafilatura, exactly as the crawler's fallback runs it

and compare each with a reference text: the site extractor's output where it is
usable, else trafilatura's. Per source and method: how often the method is
usable (>= MIN_ARTICLE_CHARS), recall of the reference's words, precision
(share of the method's words that are in the reference: low = boilerplate
added), and "Baca juga"-style boilerplate lines.

Read-only: it SELECTs links of saved articles and GETs them with the crawl's
headers, one source at a time with a pause between requests. Nothing is written.

Usage:
    venv\\Scripts\\python.exe scripts/experiments/probe_extractor_order.py --per-source 4
    venv\\Scripts\\python.exe scripts/experiments/probe_extractor_order.py --website KOMPAS,TEMPO --per-source 6

First run + conclusions: EXPERIMENTS.md, 2026-09-29 "DBT-05: extractor order, measured".
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import MIN_ARTICLE_CHARS  # noqa: E402
from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

BOILERPLATE = re.compile(r"\b(baca juga|baca selengkapnya|simak juga|lihat juga|advertisement|scroll to continue|"
                         r"artikel ini telah tayang|ikuti berita|download aplikasi)\b", re.I)
ARTICLE_TYPES = {"newsarticle", "article", "reportagenewsarticle", "analysisnewsarticle", "blogposting"}


def as_text(extracted) -> str:
    if not extracted:
        return ""
    return extracted if isinstance(extracted, str) else "\n".join(str(p) for p in extracted)


def words(t: str) -> set:
    return set(re.findall(r"\w+", t.lower()))


def jsonld_body(soup) -> str:
    """articleBody of the first article-typed JSON-LD object (top level, list or @graph)."""
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if not isinstance(obj, dict):
                continue
            stack.extend(obj.get("@graph", []) if isinstance(obj.get("@graph"), list) else [])
            types = obj.get("@type")
            types = {t.lower() for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)}
            if types & ARTICLE_TYPES and isinstance(obj.get("articleBody"), str):
                return obj["articleBody"]
    return ""


def sample_links(website, n):
    with SQLAlchemyClient().get_session() as s:
        return [r[0] for r in s.execute(text(
            "SELECT s.link FROM sitemaps s JOIN articles a USING (sitemap_id) WHERE s.sources = :w "
            "ORDER BY s.posted_at DESC, s.sitemap_id DESC LIMIT :n"), {"w": website, "n": n})]


def measure(crawler, link):
    url = link.replace("?page=all", "") if crawler.website_name == "JPNN" else link
    soup = crawler.page_loader.get_soup(url)
    if not soup:
        return None
    try:
        site = as_text(crawler._get_whole_text(soup))
    except Exception:  # noqa: BLE001 -- a dead selector raising is itself the result
        site = ""
    out = {"site": site, "jsonld": jsonld_body(soup), "traf": as_text(crawler._trafilatura_fallback(soup))}
    ref_name = "site" if len(site) >= MIN_ARTICLE_CHARS else "traf"
    ref = words(out[ref_name])
    row = {"ref": ref_name}
    for name, t in out.items():
        w = words(t)
        row[name] = {
            "usable": len(t) >= MIN_ARTICLE_CHARS,
            "chars": len(t),
            "recall": len(ref & w) / len(ref) if ref else 0.0,
            "precision": len(ref & w) / len(w) if w else 0.0,
            "boiler": len(BOILERPLATE.findall(t)),
        }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--website", help="comma-separated; default every registered crawler")
    ap.add_argument("--per-source", type=int, default=4)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--json", help="also write the raw rows here")
    args = ap.parse_args()
    sources = args.website.split(",") if args.website else sorted(CRAWLER_DICT)
    raw = {}
    print(f"{'source':15} {'n':>2} {'ref':>4} | {'method':6} {'usable':>6} {'recall':>6} {'prec':>5} {'chars':>6} {'boil':>4}")
    for src in sources:
        crawler = CRAWLER_DICT[src]
        rows = []
        for link in sample_links(src, args.per_source):
            try:
                r = measure(crawler, link)
            except Exception as e:  # noqa: BLE001
                r = None
                print(f"  {src}: {link[:60]} failed: {type(e).__name__}")
            if r:
                rows.append(r)
            time.sleep(args.pause)
        raw[src] = rows
        if not rows:
            print(f"{src:15}  0   -- no page fetched")
            continue
        refs = defaultdict(int)
        for r in rows:
            refs[r["ref"]] += 1
        ref = max(refs, key=refs.get)
        for m in ("site", "jsonld", "traf"):
            n = len(rows)
            usable = sum(r[m]["usable"] for r in rows)
            rec = sum(r[m]["recall"] for r in rows) / n
            prec = sum(r[m]["precision"] for r in rows) / n
            chars = sum(r[m]["chars"] for r in rows) // n
            boil = sum(r[m]["boiler"] for r in rows)
            head = f"{src:15} {n:2} {ref:>4}" if m == "site" else " " * 23
            print(f"{head} | {m:6} {usable:3}/{n:<2} {rec:6.2f} {prec:5.2f} {chars:6} {boil:4}", flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)


if __name__ == "__main__":
    main()
