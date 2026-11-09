#!/usr/bin/env python3
"""
QA probe (SYS-08, #26 / SRC-09, #57): which Crawler subclasses silently inherit an
abstract base method instead of implementing it?

`Crawler` is a plain class, not an `abc.ABC`, so `@abstractmethod` on it is
decorative: a subclass that forgets an override inherits a no-op returning None.
That is exactly what made VIVA save 0 of 39,262 sitemaps for four months (SYS-08).
The SYS-08 fix repaired VIVA and typed `NewsDetailsModel.reporter` as Optional, but
did not make the base class enforce anything -- so this sweep is the only way to
know whether another source is sitting on the same gap right now.

    python scripts/experiments/probe_missing_crawler_overrides.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

REQUIRED = ["_get_branches", "_get_whole_text", "_get_reporter_from_text"]
OPTIONAL = ["_scrape", "_get_link"]
METHODS = REQUIRED + OPTIONAL


def inherits_base(cls, name):
    own = getattr(cls, name, None)
    base = getattr(Crawler, name, None)
    return getattr(own, "__func__", own) is getattr(base, "__func__", base)


def main():
    missing = {m: [] for m in METHODS}
    print(f"{'SOURCE':16s} " + " ".join(f"{m[1:]:>20s}" for m in METHODS))
    for name, inst in sorted(CRAWLER_DICT.items()):
        cells = []
        for m in METHODS:
            base = inherits_base(type(inst), m)
            cells.append("BASE" if base else "own")
            if base:
                missing[m].append(name)
        print(f"{name:16s} " + " ".join(f"{c:>20s}" for c in cells))

    print()
    for m in REQUIRED:
        if missing[m]:
            print(f"!! NOT OVERRIDDEN -> {m}: {', '.join(missing[m])}")
            print("   base returns:", " ".join(l.strip() for l in
                                                inspect.getsource(getattr(Crawler, m)).strip().splitlines()))
    if not any(missing[m] for m in REQUIRED):
        print("All sources override every required method.")


if __name__ == "__main__":
    main()
