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

# Same vocabulary SRC-34 proposes for the branch-level deny-list.
SOFT = re.compile(
    r"sport|bola|olahraga|showbiz|hiburan|entertain|seleb|celeb|lifestyle|gaya-?hidup|"
    r"fashion|kuliner|food|resep|travel|wisata|otomotif|religi|kalam|ramadan|hype|"
    r"\blife\b|korea|fiction|\bmen\b|\bwomen\b|games|quiz|horoskop|zodiak|video|photo|foto|"
    r"english|health|sehat|kesehatan|tekno|gadget|musik|film|movie|kpop|jelita|nova|nakita|"
    r"intisari|bobo|hai\b|cewekbanget|stylo|gridoto|motorplus|idea|ecotainment|tainment",
    re.I,
)
FINANCE = re.compile(r"ekonomi|bisnis|finan|keuangan|uang|saham|bursa|invest|makro|business|econ|market|emiten", re.I)


def probe(name, crawler):
    try:
        soup = crawler.page_loader.get_soup(crawler.website_url)
        if not soup:
            return name, "NO_INDEX", {}
        branches = crawler._get_branches(soup)
        return name, "OK", branches
    except Exception as e:  # noqa: BLE001 -- report, don't die
        return name, f"ERROR {type(e).__name__}: {str(e)[:80]}", {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", default=None)
    args = ap.parse_args()
    names = [w.strip().upper() for w in args.website.split(",")] if args.website else sorted(CRAWLER_DICT)
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(probe, n, CRAWLER_DICT[n]): n for n in names}
        for f in as_completed(futs):
            rows.append(f.result())
    rows.sort()
    print(f"{'source':16} {'status':10} {'n':>3} {'soft':>4} {'fin':>3}  keys")
    for name, status, branches in rows:
        keys = list(branches)
        soft = [k for k in keys if SOFT.search(k)]
        fin = [k for k in keys if FINANCE.search(k)]
        url_keys = [k for k in keys if k.startswith("http")]
        shown = ", ".join(keys[:12]) + (f" … +{len(keys) - 12}" if len(keys) > 12 else "")
        flag = " URL-KEYS" if url_keys else ""
        print(f"{name:16} {status:10} {len(keys):3d} {len(soft):4d} {len(fin):3d}  {shown}{flag}")
        if soft:
            print(f"{'':16} soft -> {', '.join(soft[:15])}")


if __name__ == "__main__":
    main()
