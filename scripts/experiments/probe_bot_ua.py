#!/usr/bin/env python3
"""
SYS-70 (#218): would an honest bot User-Agent still be served, and what does
each source's robots.txt ask of a crawler?

For every scheduled source: fetch its sitemap index and one recently saved
article (from `sitemaps`, read-only) with (a) the page loader's current
browser UA and (b) a bot UA, and read robots.txt for `Crawl-delay` and
whether the bot UA may fetch the index and the article. Sequential, one
request at a time with a pause, ~5 requests per source.

    venv\\Scripts\\python.exe scripts/experiments/probe_bot_ua.py
    venv\\Scripts\\python.exe scripts/experiments/probe_bot_ua.py --only KUMPARAN,DETIK

First run + conclusions: EXPERIMENTS.md, "SYS-66/SYS-70: bot User-Agent across the fleet, fetch share of run time, ...".
"""
import argparse
import os
import sys
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.crawler_url_list import WEB_URL_DICT  # noqa: E402
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

BOT_UA = "NewsAggregatorBot/1.0"
PAUSE_S = 1.0


def fetch(url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=(10, 20), allow_redirects=True)
        return f"{r.status_code} {len(r.content) // 1024}KB"
    except Exception as e:  # noqa: BLE001 -- a probe reports, never raises
        return f"EXC {type(e).__name__}"
    finally:
        time.sleep(PAUSE_S)


def robots(url):
    parts = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = requests.get(f"{parts.scheme}://{parts.netloc}/robots.txt", headers={"User-Agent": BOT_UA}, timeout=(10, 20))
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        status = r.status_code
    except Exception as e:  # noqa: BLE001
        return None, f"EXC {type(e).__name__}"
    finally:
        time.sleep(PAUSE_S)
    return rp, status


def run(only):
    browser = dict(RequestsPageLoader().headers)
    bot = dict(browser, **{"User-Agent": BOT_UA})
    with SQLAlchemyClient().get_session() as s:
        recent = {r[0]: r[1] for r in s.execute(text(
            "SELECT DISTINCT ON (sources) sources, link FROM sitemaps "
            "WHERE crawl_status = 'saved' ORDER BY sources, sitemap_id DESC"))}
    print(f"{'SOURCE':14s} {'index browser':14s} {'index bot':14s} {'article browser':16s} {'article bot':14s} "
          f"robots  crawl-delay  bot-may(index/article)")
    for name in sorted(recent):
        if only and name not in only:
            continue
        index_url = WEB_URL_DICT.get(name) if isinstance(WEB_URL_DICT, dict) else None
        index_url = getattr(index_url, "value", index_url)
        article = recent[name]
        row = [name]
        for u in (index_url, article):
            if not u:
                row += ["-", "-"]
                continue
            row += [fetch(u, browser), fetch(u, bot)]
        rp, rstatus = robots(article)
        delay = rp.crawl_delay(BOT_UA) if rp else None
        may = (f"{rp.can_fetch(BOT_UA, index_url) if index_url else '-'}/{rp.can_fetch(BOT_UA, article)}"
               if rp else "-")
        print(f"{row[0]:14s} {row[1]:14s} {row[2]:14s} {row[3]:16s} {row[4]:14s} {str(rstatus):7s} "
              f"{str(delay):12s} {may}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    run({x.strip().upper() for x in a.only.split(",") if x.strip()})
