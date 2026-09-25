"""Which branches does a crawler still LIST although `category_gate` denies their
key? Read-only: fetches each registered crawler's sitemap index once, runs its
real `_get_branches` and the shipped `drop_soft_branches`, and asks the shipped
`category_gate` about every kept key.

Found for SRC-50 (#162): DETIK kept `edu/edutainment`, whose rows the category
gate denies through the `tainment` stem, so every row it listed was fetched and
extracted only to be rejected. SRC-49 was the opposite mismatch: a branch
dropped by name whose stored rows the category gate did NOT deny.

Only meaningful for crawlers that store the branch key as `sitemaps.category`.
A crawler that derives a per-article section from the URL
(`derives_category_from_url()`, MEDIAINDONESIA) is reported, but its branch
key is not what gets stored.

    venv\\Scripts\\python.exe scripts/experiments/probe_branch_category_mismatch.py [--website A,B]
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402
from newscrawler.core.importance_filter import category_gate  # noqa: E402


def probe(name):
    crawler = CRAWLER_DICT[name]
    try:
        soup = crawler.page_loader.get_soup(crawler.website_url)
        listed = crawler._get_branches(soup) if soup else {}
    except Exception as e:  # noqa: BLE001 -- report, don't die
        return name, "ERROR %s" % type(e).__name__, []
    kept = crawler.drop_soft_branches(listed)
    return name, "OK" if listed else "NO_INDEX", sorted(k for k in kept if category_gate(k, name) == "deny")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", default=None)
    args = ap.parse_args(argv)
    names = [w.strip().upper() for w in args.website.split(",")] if args.website else sorted(CRAWLER_DICT)
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = sorted(ex.map(probe, names))
    total = 0
    for name, status, mismatched in rows:
        derived = " (stores per-article section)" if CRAWLER_DICT[name].derives_category_from_url() else ""
        if mismatched or status != "OK":
            print("%-16s %-10s %3d  %s%s" % (name, status, len(mismatched), ", ".join(mismatched), derived))
        total += len(mismatched)
    print("\n%d kept branch(es) whose key the category gate denies" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
