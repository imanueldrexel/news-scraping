"""SRC-58 (#231): which listed (non-soft) branches can never load, and why -- without fetching them.

For each source: the branch list after the soft/archive drop, each branch URL's host, whether the
URL parses (a `<loc>` like 'https://.kontan.co.id/...' does not), and how the host resolves
(socket.getaddrinfo once per host: ok / NXDOMAIN-like / temporary failure). With --fetch, every
branch is also requested once (one attempt, no retries) to see which answer 404/410.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_dead_branches.py --website PIKIRANRAKYAT,KONTAN
    venv\\Scripts\\python.exe scripts\\experiments\\probe_dead_branches.py --website KONTAN --fetch
"""
import argparse
import collections
import os
import socket
import sys
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import requests  # noqa: E402

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402


def resolve(host: str) -> str:
    try:
        socket.getaddrinfo(host, 443)
        return "ok"
    except socket.gaierror as e:
        return f"gaierror {e.errno}: {e.strerror}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--website", required=True)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)
    print(f"socket.EAI_NONAME={getattr(socket, 'EAI_NONAME', None)} EAI_AGAIN={getattr(socket, 'EAI_AGAIN', None)}")
    for name in args.website.split(","):
        crawler = CRAWLER_DICT[name.strip()]
        listed = crawler.list_branches()
        if listed is None:
            print(f"\n### {name}: index did not load ({getattr(crawler, 'last_index_error', '?')})")
            continue
        kept = crawler.drop_soft_branches(listed)
        hosts = collections.Counter()
        verdicts = {}
        for key, link in kept.items():
            parsed = urlparse(link or "")
            host = parsed.hostname or ""
            if not host or "" in host.split("."):
                verdicts[key] = f"MALFORMED {link!r}"
                continue
            hosts[host] += 1
        status = {}
        started = time.monotonic()
        for host in hosts:
            status[host] = resolve(host)
        dns_s = time.monotonic() - started
        dead = {h for h, s in status.items() if s != "ok"}
        print(f"\n### {name}: {len(listed)} listed, {len(kept)} kept, {len(hosts)} hosts, "
              f"{len(dead)} do not resolve ({sum(hosts[h] for h in dead)} branches); DNS {dns_s:.1f}s")
        for key, v in verdicts.items():
            print(f"  {key}: {v}")
        for h in sorted(dead):
            print(f"  {h} ({hosts[h]} branch(es)): {status[h]}")
        if args.fetch:
            for key, link in kept.items():
                host = urlparse(link or "").hostname or ""
                if key in verdicts or host in dead:
                    continue
                try:
                    r = requests.get(link, timeout=(10, 20), headers=crawler.page_loader.headers_for(link))
                    if r.status_code != 200:
                        print(f"  {key}: HTTP {r.status_code} {link}")
                except Exception as e:  # noqa: BLE001 -- urllib3's LocationParseError on a bad redirect is not
                    print(f"  {key}: {type(e).__name__}: {str(e)[:80]} {link}")     # a RequestException
    return 0


if __name__ == "__main__":
    sys.exit(main())
