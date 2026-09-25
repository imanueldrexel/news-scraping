"""SRC-51 (#163): is OKEZONE's `news:publication_date` the article's date? And
which URL shapes carry a date of their own?

Read-only. Fetches every branch sitemap OKEZONE lists (its real `_get_branches` +
the shipped soft-branch drop) and, per branch, reports how many <url> there are,
how many distinct publication dates the file claims, and the date the URL
itself carries -- through the same `date_from_url` the crawler uses. Then it
tabulates the stored `sitemaps.link` shapes.

    venv\\Scripts\\python.exe scripts/experiments/probe_okezone_dates.py [--no-db]
"""
import argparse
import collections
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402
from newscrawler.infrastructure.datasource.scrapers.okezone.okezone_crawler import OkezoneCrawler  # noqa: E402


def shape(link):
    """The URL with every digit run replaced, host kept: groups links by pattern."""
    return re.sub(r"\d+", "N", re.sub(r"^https?://", "", link or "").split("?")[0])[:70]


def _stamp(url):
    """The file's own claimed date for one <url>, to the minute: a render-time
    stamp shows up as one value for the whole file."""
    el = url.find("news:publication_date") or url.find("lastmod")
    return el.get_text(" ").strip()[:16] if el else None


def branch_report(crawler, key, link):
    soup = crawler.page_loader.get_soup(link)
    if not soup:
        return key, None
    urls = soup.find_all("url")
    pub = {_stamp(u) for u in urls}
    url_dates = [OkezoneCrawler.date_from_url((u.find("loc") or soup).get_text(" ").strip()) for u in urls]
    dated = [d for d in url_dates if d]
    shapes = collections.Counter(shape((u.find("loc") or soup).get_text(" ").strip()) for u in urls)
    return key, {
        "n": len(urls), "pub_distinct": len(pub), "pub_sample": sorted(p for p in pub if p)[:2],
        "url_dated": len(dated), "url_min": min(dated).strftime("%Y-%m-%d") if dated else "-",
        "url_max": max(dated).strftime("%Y-%m-%d") if dated else "-",
        "undated_shapes": [s for s, _ in shapes.most_common() if not re.search(r"/N/N/N/", s)][:2],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args(argv)
    crawler = CRAWLER_DICT["OKEZONE"]
    index = crawler.page_loader.get_soup(crawler.website_url)
    branches = crawler.drop_soft_branches(crawler._get_branches(index))
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = sorted(ex.map(lambda kv: branch_report(crawler, *kv), branches.items()))
    total = dated = 0
    print("%-28s %4s %5s %5s  %-10s %-10s  %s" % ("branch", "urls", "pub#", "dated", "url_min", "url_max", "undated shapes"))
    for key, r in rows:
        if r is None:
            print("%-28s  (fetch failed)" % key)
            continue
        total += r["n"]
        dated += r["url_dated"]
        print("%-28s %4d %5d %5d  %-10s %-10s  %s" % (key, r["n"], r["pub_distinct"], r["url_dated"], r["url_min"],
                                                     r["url_max"], "; ".join(r["undated_shapes"])))
    print("\nlive: %d <url> in %d kept branches, %d with a date in the URL (%.1f%%)"
          % (total, len(rows), dated, 100.0 * dated / max(total, 1)))
    if args.no_db:
        return 0
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    with SQLAlchemyClient().get_session() as s:
        stored = s.execute(text("SELECT link, posted_at FROM sitemaps WHERE sources = 'OKEZONE'")).fetchall()
    shapes = collections.Counter(shape(r.link) for r in stored)
    undated = [r for r in stored if OkezoneCrawler.date_from_url(r.link) is None]
    agree = sum(1 for r in stored if (d := OkezoneCrawler.date_from_url(r.link)) and int(d.strftime("%Y%m%d")) == r.posted_at)
    print("\nstored: %d rows, %d distinct posted_at, %d undated by URL, %d already agree with the URL date"
          % (len(stored), len({r.posted_at for r in stored}), len(undated), agree))
    for sh, n in shapes.most_common(12):
        print("  %6d  %s" % (n, sh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
