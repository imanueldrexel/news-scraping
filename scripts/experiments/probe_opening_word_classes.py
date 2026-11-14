#!/usr/bin/env python3
"""
QA 2026-11-08 (#450 / #451): which archive signal separates the opening words a follow-up shares with its thread (time
words, particles, hedges: "Kemarin / Kok / Kira-kira harganya ...?") from common nouns that are a new subject ("Gula /
Beras / Timah harganya ...?")? Both are written in lower case mid-sentence, so ADR-032's class cannot tell them apart.

For each probe word this prints its lower-case mid-sentence uses and the share of them that come right after a
governing word (a lower-case content word: "harga gula", "impor beras") and right before a determiner ("gula ini",
"beras itu"). Read-only on the DB.

    venv\\Scripts\\python.exe scripts/experiments/probe_opening_word_classes.py --limit 60000
"""
import argparse
import collections
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text  # noqa: E402

from newscrawler.core import story_words  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

NOUNS = "gula beras nikel timah mandiri emas saham rupiah minyak semen bank batu bumi jasa cabai bawang kopi".split()
OTHERS = ("kemarin besok lusa tadi semalam kira-kira kok masa konon nanti kini dulu barusan mungkin benar sungguh "
          "memang ternyata pasti tiba-tiba mendadak sekarang").split()
WORD = re.compile(r"[^\W\d_][\w-]*")
_OPENS_SENTENCE = set(".?!\"'“”‘’:;(\n")
DETERMINERS = {"ini", "itu", "tersebut"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    args = ap.parse_args()
    probe = set(NOUNS) | set(OTHERS)
    uses, governed, determined = collections.Counter(), collections.Counter(), collections.Counter()
    prev_words = collections.defaultdict(collections.Counter)
    engine = create_engine(SQLAlchemyClient().database_uri)
    with engine.connect() as conn:
        rows = conn.execution_options(stream_results=True, yield_per=2000).execute(
            text("SELECT extracted_text FROM articles WHERE extracted_text IS NOT NULL "
                 "ORDER BY sitemap_id DESC LIMIT :n"), {"n": args.limit})
        for (body,) in rows:
            tokens = list(WORD.finditer(body))
            for i, m in enumerate(tokens):
                w = m.group(0)
                if w.lower() not in probe or not w[0].islower():
                    continue
                before = body[:m.start()].rstrip()[-1:]
                if not before or before in _OPENS_SENTENCE:
                    continue
                uses[w] += 1
                if i and body[tokens[i - 1].end():m.start()].strip() == "":
                    p = tokens[i - 1].group(0)
                    if p[0].islower() and p not in story_words.STOPWORDS:
                        governed[w] += 1
                        prev_words[w][p] += 1
                if i + 1 < len(tokens) and tokens[i + 1].group(0).lower() in DETERMINERS:
                    determined[w] += 1
    for group, words in (("nouns", NOUNS), ("others", OTHERS)):
        print(f"--- {group}")
        for w in words:
            n = max(uses[w], 1)
            top = ", ".join(f"{p} {c}" for p, c in prev_words[w].most_common(6))
            print(f"{w:12s} uses {uses[w]:6d}  governed {governed[w] / n:5.2f}  determined {determined[w] / n:5.2f}"
                  f"  | {top}")


if __name__ == "__main__":
    main()
