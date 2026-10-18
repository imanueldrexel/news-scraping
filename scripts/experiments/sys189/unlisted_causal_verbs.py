"""SYS-189 (#390): where do the arcs use causal verbs `causal_check._KINDS` does not hold? (read-only, no DB, no LLM)

Prints every sentence of the stored arc prose (arcs-v4/v5/v6, hari_ini + latar/agenda) holding one of the candidate
forms, so each can be read as causal or not, and counts them per form.

    venv\Scripts\python.exe scripts/experiments/sys189/unlisted_causal_verbs.py
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
from replay_story_arcs import back_stories_from_markdown, run_edition, run_key  # noqa: E402

from newscrawler.core import causal_check as cc  # noqa: E402

FORMS = (r"didorong|mendorong|dipengaruhi|memengaruhi|mempengaruhi|ditopang|menopang|berkat|seiring|membuat|"
         r"menimbulkan|ditimbulkan|menekan|tertekan|ditekan|dilatarbelakangi|bermula\s+dari|dampak|berdampak|"
         r"menyusul|imbas")
PATTERN = re.compile(rf"\b(?:{FORMS})\b", re.IGNORECASE)


def main():
    counts = collections.Counter()
    for run in ("arcs-v4", "arcs-v5", "arcs-v6"):
        out_dir = os.path.join(ROOT, "digests", "preview", run)
        key = run_key(out_dir)
        for day in sorted(key):
            for story in back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                                    run_edition(out_dir, key, day, "today"), set()):
                for field in ("hari_ini", "back"):
                    for sentence in cc.sentences(story[field]):
                        for m in PATTERN.finditer(sentence):
                            counts[m.group(0).lower()] += 1
                            print(f"{run} {day} {field:8} [{m.group(0)}] {sentence[:170]}")
    print("\n" + ", ".join(f"{w} {n}" for w, n in counts.most_common()))


if __name__ == "__main__":
    main()
