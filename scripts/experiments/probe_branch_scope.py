"""Which sources' live branch sets contain soft verticals (sport/showbiz/
lifestyle/...) and which are already hard-news-only? Read-only: fetches each
registered crawler's sitemap index once and runs its real `_get_branches`.

Filed for SRC-34 (#124) / the 2026-09-20 scope change: SRC-34 only widens the
nine finance-narrowed crawlers; this shows what the *other* twenty list today,
so the branch-level soft deny-list can be applied uniformly instead of per
ticket.

    venv\\Scripts\\python.exe scripts/experiments/probe_branch_scope.py [--website A,B]
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402

# SRC-43 (#146): this script used to carry its own SOFT regex. It was a
# DIFFERENT predicate from the one that ships -- unbounded substrings, and a
# vocabulary that included `otomotif`, `kesehatan`, `tekno`, `video`/`foto`,
# all of which SRC-35's sampling deliberately KEPT -- so the two disagreed and
# this script's numbers were not the pipeline's. A fleet claim is verified with
# the shipped function or it is not verified. `is_soft_branch` is a classmethod,
# so per-crawler SOFT_BRANCH_EXCEPTIONS are honoured too.
FINANCE = re.compile(r"ekonomi|bisnis|finan|keuangan|uang|money|saham|bursa|invest|makro|business|econ|market|emiten", re.I)

# Sources whose live index still yields URL-shaped keys, each against its
# ticket. --fail-on-url-keys exits 0 while only these appear, so the check can
# be wired into a run without going red on known, tracked work.
URL_KEY_WHITELIST = {"VIVA": "SRC-33 (#119)"}


def probe(name, crawler):
    try:
        branches = crawler.list_branches()  # every index (SRC-38)
        if branches is None:
            return name, "NO_INDEX", {}
        return name, "OK", branches
    except Exception as e:  # noqa: BLE001 -- report, don't die
        return name, f"ERROR {type(e).__name__}: {str(e)[:80]}", {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", default=None)
    ap.add_argument("--fail-on-url-keys", action="store_true",
                    help="Exit 2 if any source outside URL_KEY_WHITELIST keys a branch by its URL (SRC-43 #146)")
    args = ap.parse_args()
    names = [w.strip().upper() for w in args.website.split(",")] if args.website else sorted(CRAWLER_DICT)
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(probe, n, CRAWLER_DICT[n]): n for n in names}
        for f in as_completed(futs):
            rows.append(f.result())
    rows.sort()
    offenders = {}
    totals = [0, 0, 0, 0]
    print(f"{'source':16} {'status':10} {'n':>4} {'soft':>4} {'arch':>4} {'crawl':>5} {'fin':>3}  keys")
    for name, status, branches in rows:
        crawler = CRAWLER_DICT[name]
        keys = list(branches)
        # The shipped predicates, not copies of them -- and both of them, or
        # the table understates the drop by every archive partition (SRC-45).
        soft = [k for k in keys if crawler.is_soft_branch(k)]
        archive = [k for k in keys if not crawler.is_soft_branch(k) and crawler.is_archive_branch(k)]
        crawled = len(keys) - len(soft) - len(archive)
        fin = [k for k in keys if FINANCE.search(k)]
        url_keys = [k for k in keys if k.startswith("http")]
        totals = [totals[0] + len(keys), totals[1] + len(soft), totals[2] + len(url_keys),
                  totals[3] + len(archive)]
        if url_keys:
            offenders[name] = len(url_keys)
        shown = ", ".join(keys[:10]) + (f" … +{len(keys) - 10}" if len(keys) > 10 else "")
        flag = f" URL-KEYS={len(url_keys)}" if url_keys else ""
        print(f"{name:16} {status:10} {len(keys):4d} {len(soft):4d} {len(archive):4d} {crawled:5d} {len(fin):3d}  {shown}{flag}")
        if soft:
            print(f"{'':16} soft -> {', '.join(sorted(soft)[:15])}")
        if archive:
            print(f"{'':16} archive -> {len(archive)} partition(s), e.g. {', '.join(sorted(archive)[:3])}")

    print(f"\nfleet: {totals[0]} branches listed, {totals[1]} dropped as soft, {totals[3]} dropped as archive, "
          f"{totals[0] - totals[1] - totals[3]} crawled, {totals[2]} keyed by URL")
    untracked = {n: c for n, c in offenders.items() if n not in URL_KEY_WHITELIST}
    for name, count in sorted(offenders.items()):
        note = URL_KEY_WHITELIST.get(name, "UNTRACKED -- a <loc> must be skipped, not keyed by its URL (SRC-39 #133)")
        print(f"  URL-keyed: {name:16} {count:4d}  {note}")
    if args.fail_on_url_keys and untracked:
        print(f"\nFAIL: {len(untracked)} source(s) key branches by URL with no ticket: {', '.join(sorted(untracked))}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
