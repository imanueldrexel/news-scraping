#!/usr/bin/env python3
"""
QA 2026-11-08 (#452): `movement_words.txt` (ADR-032) admitted -nya nouns (eskalasinya, ekspornya) and nouns or
quantifiers (mayoritas, total, payung, kisaran, rata-rata) next to the words of the movement itself (tajam, tipis,
sepanjang). Does what FOLLOWS the word after a movement verb tell them apart? A word of the movement ends the
clause or is followed by a number, a function word or a time word ("melemah tajam.", "menguat tipis 0,2 persen",
"anjlok sepanjang pekan"); a noun heads a phrase ("mayoritas saham", "total aset").

For each word of the current class this prints its uses after a movement verb and the share of them followed by a
content word (a lower-case word that is no stopword, time word or other class member). Read-only on the DB.

    venv\\Scripts\\python.exe scripts/experiments/probe_movement_word_next.py --limit 60000
"""
import argparse
import collections
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from sqlalchemy import create_engine, text  # noqa: E402

from build_word_classes import MOVE  # noqa: E402
from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core import story_words  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

NEXT = re.compile(r"\s*([^\W\d_][\w-]*|\d|[^\w\s])")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    args = ap.parse_args()
    words = cc._MOVEMENT_WORDS
    uses, content = collections.Counter(), collections.Counter()
    engine = create_engine(SQLAlchemyClient().database_uri)
    with engine.connect() as conn:
        rows = conn.execution_options(stream_results=True, yield_per=2000).execute(
            text("SELECT extracted_text FROM articles WHERE extracted_text IS NOT NULL "
                 "ORDER BY sitemap_id DESC LIMIT :n"), {"n": args.limit})
        for (body,) in rows:
            for m in MOVE.finditer(body):
                w = m.group(1).lower()
                if w not in words:
                    continue
                uses[w] += 1
                n = NEXT.match(body, m.end())
                nxt = n.group(1) if n else ""
                if (nxt[:1].isalpha() and nxt[0].islower() and nxt not in story_words.STOPWORDS
                        and nxt not in cc._TIME_WORDS and nxt not in words):
                    content[w] += 1
    for w in sorted(words, key=lambda w: content[w] / max(uses[w], 1), reverse=True):
        print(f"{w:16s} uses {uses[w]:5d}  then-content {content[w] / max(uses[w], 1):5.2f}")


if __name__ == "__main__":
    main()
