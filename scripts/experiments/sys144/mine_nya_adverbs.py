"""SYS-144 (#327): which words ending in -nya are sentence adverbs (no referent) in the corpus?

A sentence adverb in -nya opens a sentence and is followed by a comma ("Sayangnya, ...", "Nantinya, ..."),
while a possessive noun ("Harganya naik") rarely is. For every -nya word in the newest N articles this
prints its count, how often it opens a sentence followed by a comma, and that share. The list is a
candidate set for a hand reading, not a classifier: "Akibatnya," and "Sebaliknya," open sentences too
and do point back. Production, read-only.

    venv\Scripts\python.exe scripts\experiments\sys144\mine_nya_adverbs.py [--articles 20000] [--top 150]
"""
import argparse
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

NYA = re.compile(r"\b[^\W\d_][\w-]*nya\b", re.UNICODE)
OPENER = re.compile(r"(?:^|[.!?]\s+|\n\s*)([^\W\d_][\w-]*nya),", re.UNICODE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", type=int, default=20000)
    ap.add_argument("--top", type=int, default=150)
    ap.add_argument("--min-count", type=int, default=30)
    args = ap.parse_args()
    total, opener = Counter(), Counter()
    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(text("SELECT extracted_text FROM articles WHERE extracted_text IS NOT NULL "
                              "ORDER BY articles_id DESC LIMIT :n"), {"n": args.articles})
        n = 0
        for (body,) in rows:
            n += 1
            for m in NYA.finditer(body):
                total[m.group(0).lower()] += 1
            for m in OPENER.finditer(body):
                opener[m.group(1).lower()] += 1
    print(f"articles={n} distinct -nya words={len(total)}")
    ranked = sorted((w for w in opener if total[w] >= args.min_count),
                    key=lambda w: (-opener[w] / total[w], -opener[w]))
    print(f"{'word':22} {'count':>7} {'opens,':>7} {'share':>6}")
    for w in ranked[:args.top]:
        print(f"{w:22} {total[w]:7d} {opener[w]:7d} {opener[w] / total[w]:6.2f}")


if __name__ == "__main__":
    main()
