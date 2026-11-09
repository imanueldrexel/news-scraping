"""SRC-29 (#111): which INEWS hosts are actually dead, host by host?

Read-only. For every host that has stored INEWS `sitemaps` rows, fetch up to
--per-host of its newest stored links through INEWS's own page loader
(`get_soup_with_reason`, the path the article crawl uses) and classify the host:
  dead   every sample failed with a per-URL reason (HTTP 404/410, soft-404)
  alive  every sample fetched
  mixed  anything else (including source-level errors: 403, 5xx, timeouts)
`www.inews.id` is sampled the same way, as the control.

    venv\\Scripts\\python.exe scripts/experiments/probe_inews_hosts.py [--per-host 3] [--json out.json]
"""
import argparse
import collections
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

HOST_RE = re.compile(r"^https?://([a-z0-9-]+)\.inews\.id/")

_SQL = text("""
    SELECT link FROM (
      SELECT link, substring(link from '^https?://([a-z0-9-]+)\\.inews\\.id/') AS host,
             ROW_NUMBER() OVER (PARTITION BY substring(link from '^https?://([a-z0-9-]+)\\.inews\\.id/')
                                ORDER BY posted_at DESC, sitemap_id DESC) AS rn
      FROM sitemaps WHERE sources = 'INEWS'
    ) t WHERE rn <= :n
""")


def fetch(loader, link):
    # get_soup_with_reason, NOT get_url_with_reason: the latter returns the
    # response for ANY HTTP status (a 404 included) and only the soup call checks
    # it. The first run of this probe used it and reported 342/342 "alive".
    soup, reason = loader.get_soup_with_reason(link)
    return link, ("ok" if soup is not None else (reason or "unknown failure"))


def classify(results):
    reasons = [r for _, r in results]
    if all(r == "ok" for r in reasons):
        return "alive"
    if all(r != "ok" and CrawlerServiceImpl._is_per_url_failure(r) for r in reasons):
        return "dead"
    return "mixed"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-host", type=int, default=3)
    ap.add_argument("--json", default=None, help="Write the per-host verdicts here")
    args = ap.parse_args(argv)
    with SQLAlchemyClient().get_session() as s:
        links = [r.link for r in s.execute(_SQL, {"n": args.per_host}).fetchall()]
    loader = CRAWLER_DICT["INEWS"].page_loader
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda l: fetch(loader, l), links))
    by_host = collections.defaultdict(list)
    for link, reason in results:
        m = HOST_RE.match(link)
        by_host[m.group(1) if m else "?"].append((link, reason))
    verdicts = {h: classify(rs) for h, rs in by_host.items()}
    counts = collections.Counter(v for h, v in verdicts.items() if h != "www")
    print("www (control): %s  %s" % (verdicts.get("www"), [r for _, r in by_host.get("www", [])]))
    print("subdomain hosts: %d  -> %s" % (sum(counts.values()), dict(counts)))
    for h in sorted(by_host):
        if h != "www" and verdicts[h] != "dead":
            print("  NOT DEAD %-18s %s" % (h, [r for _, r in by_host[h]]))
    print("reasons: %s" % dict(collections.Counter(r for _, r in results).most_common(8)))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({h: {"verdict": verdicts[h], "samples": by_host[h]} for h in by_host}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
