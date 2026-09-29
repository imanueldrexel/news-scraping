#!/usr/bin/env python3
"""
Measure where a source starts throttling article fetches (SRC-55, #201).

Read-only: it SELECTs article URLs of one source from `sitemaps` and GETs
them with the crawl's own headers. It writes nothing to the DB or FAISS.
Every request is one the scheduled crawl would make anyway, so keep runs
small and never run it inside a scheduled crawl window (07:00 / 19:00 WIB).

Modes:
  burst    -- `--workers` parallel fetches (the crawl uses MAX_WORKER), until
              `--stop-after` throttle answers (403/429) in a row or `--max`
              requests. Prints the request number of the first throttle
              answer, elapsed time, request rate, and the first throttle
              answer's headers (Retry-After, server, rate-limit headers).
  recover  -- one request every `--interval` seconds until a page is served
              again; prints how long the block lasted.
  paced    -- sequential at `--rate` requests/s up to `--max`; tells a
              count limit apart from a rate limit.

Usage (from repo root):
    venv\\Scripts\\python.exe scripts/experiments/probe_rate_limit.py --website KUMPARAN --mode burst --workers 10
    venv\\Scripts\\python.exe scripts/experiments/probe_rate_limit.py --website KUMPARAN --mode recover --interval 60
    venv\\Scripts\\python.exe scripts/experiments/probe_rate_limit.py --website KUMPARAN --mode paced --rate 1 --max 250

First run + conclusions: EXPERIMENTS.md, 2026-09-29 "SRC-55: KUMPARAN's rate limit, measured".
"""
import argparse
import concurrent.futures as cf
import os
import sys
import threading
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

import requests  # noqa: E402
from sqlalchemy import text  # noqa: E402

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

THROTTLE = {403, 429}
HEADER_HINTS = ("retry-after", "server", "x-ratelimit", "ratelimit", "cf-", "x-cache", "via", "x-amz", "x-served")


def load_urls(website, n, offset):
    """Links of the source, newest first, skipping `offset` rows so repeated
    runs do not re-request the same pages."""
    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(text(
            "SELECT link FROM sitemaps WHERE sources = :w ORDER BY posted_at DESC, sitemap_id DESC "
            "LIMIT :n OFFSET :o"), {"w": website, "n": n, "o": offset}).fetchall()
    return [r[0] for r in rows]


def fetch(url, headers):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers, timeout=(10, 27))
        return r.status_code, r.headers, time.monotonic() - t
    except requests.RequestException as e:
        return type(e).__name__, {}, time.monotonic() - t


def interesting_headers(h):
    return {k: v for k, v in h.items() if any(k.lower().startswith(p) for p in HEADER_HINTS)}


def burst(urls, headers, workers, stop_after, max_n):
    lock = threading.Lock()
    state = {"n": 0, "streak": 0, "first": None, "stop": False, "statuses": []}
    t0 = time.monotonic()

    def one(url):
        if state["stop"]:
            return
        status, h, dt = fetch(url, headers)
        with lock:
            state["n"] += 1
            n = state["n"]
            state["statuses"].append(status)
            if status in THROTTLE:
                state["streak"] += 1
                if state["first"] is None:
                    state["first"] = (n, time.monotonic() - t0, status, interesting_headers(h))
                if state["streak"] >= stop_after:
                    state["stop"] = True
            else:
                state["streak"] = 0
            if n >= max_n:
                state["stop"] = True

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, urls[:max_n]))
    elapsed = time.monotonic() - t0
    n = state["n"]
    served = sum(1 for s in state["statuses"] if s == 200)
    print(f"requests={n} served(200)={served} elapsed={elapsed:.1f}s rate={n / elapsed:.1f}/s workers={workers}")
    counts = {}
    for s in state["statuses"]:
        counts[s] = counts.get(s, 0) + 1
    print(f"status counts: {counts}")
    if state["first"]:
        k, at, status, hh = state["first"]
        print(f"first throttle answer: request #{k} at {at:.1f}s (HTTP {status}); headers: {hh}")
    else:
        print("no throttle answer")


def recover(url_iter, headers, interval, max_wait):
    t0 = time.monotonic()
    for url in url_iter:
        status, h, _ = fetch(url, headers)
        since = time.monotonic() - t0
        print(f"t+{since:6.0f}s HTTP {status} {interesting_headers(h) if status in THROTTLE else ''}", flush=True)
        if status == 200:
            print(f"served again after {since:.0f}s")
            return
        if since > max_wait:
            print(f"still throttled after {since:.0f}s; giving up")
            return
        time.sleep(interval)


def paced(urls, headers, rate, max_n):
    t0 = time.monotonic()
    first = None
    counts = {}
    for i, url in enumerate(urls[:max_n], 1):
        status, h, _ = fetch(url, headers)
        counts[status] = counts.get(status, 0) + 1
        if status in THROTTLE and first is None:
            first = (i, time.monotonic() - t0, interesting_headers(h))
            print(f"first throttle answer: request #{i} at {first[1]:.1f}s; headers: {first[2]}", flush=True)
        wait = t0 + i / rate - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    elapsed = time.monotonic() - t0
    print(f"requests={min(len(urls), max_n)} elapsed={elapsed:.1f}s rate={min(len(urls), max_n) / elapsed:.2f}/s")
    print(f"status counts: {counts}")
    if first is None:
        print("no throttle answer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--website", required=True)
    ap.add_argument("--mode", choices=("burst", "recover", "paced"), required=True)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--stop-after", type=int, default=5)
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--interval", type=float, default=60)
    ap.add_argument("--max-wait", type=float, default=3600)
    ap.add_argument("--offset", type=int, default=0, help="skip this many newest links")
    args = ap.parse_args()

    headers = RequestsPageLoader().headers
    urls = load_urls(args.website, max(args.max, 400), args.offset)
    print(f"{args.website}: {len(urls)} links loaded (offset {args.offset}); mode={args.mode} "
          f"at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if args.mode == "burst":
        burst(urls, headers, args.workers, args.stop_after, args.max)
    elif args.mode == "recover":
        recover(iter(urls), headers, args.interval, args.max_wait)
    else:
        paced(urls, headers, args.rate, args.max)


if __name__ == "__main__":
    main()
