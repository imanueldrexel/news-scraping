#!/usr/bin/env python3
"""
ADR-032 (QA 2026-11-06, #440 / #448 / #449): build the two word classes the gates read from how the archive writes
its words, instead of from hand lists that every held-out probe outgrew (ADR-031). Read-only on the DB.

  newscrawler/web/common_words.txt   words the archive writes in lower case where no sentence starts, in at least
                                     half of those uses (kemarin 1469/7, kok 321/12; Sritex 0/10, Antam 22/1768).
                                     `followup._opening_subject`: a capitalised opening word is the follow-up's own
                                     subject only when it is no common word ("Kemarin harganya ...?" vs
                                     "Sritex ujung-ujungnya ...?"). A new name is in no snapshot, so it stays a name.
  newscrawler/core/movement_words.txt words that follow a market-movement verb ("melemah tajam", "menguat tipis",
                                     "anjlok sepanjang", "meningkat signifikan") at least MOVE_RATIO times as often,
                                     per use, as a noun-taking cause marker ("akibat aksi jual", "dipicu
                                     kekhawatiran"): they say how or when something moved, not why.
                                     `causal_check._cause_follows`: "tertekan tajam" states no cause.

Run, then review the diff of both files before committing:
    venv\\Scripts\\python.exe scripts/build_word_classes.py
"""
import collections
import os
import re
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_PATH = os.path.join(ROOT, "newscrawler", "web", "common_words.txt")
MOVEMENT_PATH = os.path.join(ROOT, "newscrawler", "core", "movement_words.txt")

MIN_LOWER = 5          # a word written in lower case fewer times is too rare to call common
MIN_MOVE = 5           # ... or to call a movement word
MOVE_RATIO = 3.0       # per use, after a movement verb at least this many times as often as after a cause marker

WORD = re.compile(r"[^\W\d_][\w-]*")
_OPENS_SENTENCE = set(".?!\"'“”‘’:;(\n")
# Unambiguous market-movement verbs. Not "naik" / "turun": they also mean get on / off ("naik kereta", "penumpang
# turun"), which brought in nouns.
MOVE = re.compile(r"\b(?:melemah|menguat|anjlok|merosot|terkoreksi|menanjak|melonjak|ambles|ambruk|menurun|meningkat|"
                  r"terdepresiasi|terapresiasi|terjun|meroket)\s+(?:oleh\s+)?([^\W\d_][\w-]*)", re.IGNORECASE)
# Cause markers that take a noun phrase. Not "karena" / "lantaran": they take a clause ("karena jika ...").
CAUSE = re.compile(r"\b(?:akibat|imbas|dipicu|disebabkan|terdampak|dampak)\s+(?:oleh\s+|dari\s+)?([^\W\d_][\w-]*)",
                   re.IGNORECASE)
# A numeral opens a counted cause ("tertekan dua sentimen negatif") as often as a counted movement ("melemah dua
# persen"): never a movement word.
_NUMERALS = frozenset("satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas belas puluh ratus ribu "
                      "seratus seribu".split())


def count(texts):
    lower, upper = collections.Counter(), collections.Counter()
    moved, caused = collections.Counter(), collections.Counter()
    n = 0
    for body in texts:
        n += 1
        for m in WORD.finditer(body):
            word = m.group(0)
            if any(ch.isdigit() for ch in word):
                continue
            before = body[:m.start()].rstrip()[-1:]
            if not before or before in _OPENS_SENTENCE:
                continue
            (upper if word[0].isupper() else lower)[word.lower()] += 1
        for m in MOVE.finditer(body):
            moved[m.group(1).lower()] += 1
        for m in CAUSE.finditer(body):
            caused[m.group(1).lower()] += 1
    return n, lower, upper, moved, caused


def classes(lower, upper, moved, caused):
    common = {w for w, n in lower.items() if n >= MIN_LOWER and n >= upper[w]}
    m_total, c_total = max(sum(moved.values()), 1), max(sum(caused.values()), 1)
    movement = {w for w, n in moved.items()
                if n >= MIN_MOVE and w in common and w not in _NUMERALS
                and n / m_total >= MOVE_RATIO * caused[w] / c_total}
    return common, movement


def write(path, words, header):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in header:
            f.write(f"# {line}\n")
        for w in sorted(words):
            f.write(w + "\n")


def main():
    engine = create_engine(SQLAlchemyClient().database_uri)
    with engine.connect() as conn:
        rows = conn.execution_options(stream_results=True, yield_per=2000).execute(
            text("SELECT extracted_text FROM articles WHERE extracted_text IS NOT NULL"))
        n, lower, upper, moved, caused = count(r[0] for r in rows)
    common, movement = classes(lower, upper, moved, caused)
    built = f"built {date.today().isoformat()} by scripts/build_word_classes.py from {n} articles (ADR-032)"
    write(COMMON_PATH, common, [built, f"lower case where no sentence starts: >= {MIN_LOWER} uses and >= half"])
    write(MOVEMENT_PATH, movement, [built, f"after a movement verb >= {MIN_MOVE} times and >= {MOVE_RATIO:g}x the "
                                           "per-use rate after a cause marker; common words only"])
    print(f"{n} articles: {len(common)} common words, {len(movement)} movement words")


if __name__ == "__main__":
    main()
