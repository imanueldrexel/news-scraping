"""SYS-188 (#389): which words of each backed causal half does its link NOT cover? (read-only, no LLM)

A stricter coverage rule (every name, every noun, every word) costs exactly the backed claims whose missed words
fall in the class it stops tolerating. For each causal word of the stored replays (arcs-v4/v5/v6) that the gate
backs, this prints the best link's missed words per half, each marked name (N), affixed verb-like (V) or other (W).

    venv\Scripts\python.exe scripts/experiments/sys188/missed_words.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments", "sys152"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
import recheck_causes as rc  # noqa: E402  (loads .env)
import psycopg2  # noqa: E402

from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core import story_words  # noqa: E402


def missed(half: str, side: str) -> list:
    theirs = cc._roots(side)
    out = []
    for w, is_name in story_words.content_words(half).items():
        if w in cc._GENERIC or w in cc._NEGATORS or cc._meets(cc._root(w), theirs):
            continue
        out.append(f"{w}({'N' if is_name else 'V' if cc._root(w) != w else 'W'})")
    return out


def main():
    conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                            user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                            dbname=os.environ["POSTGRES_DB_NAME"])
    conn.set_session(readonly=True)
    cur = conn.cursor()
    for run in rc.RUNS:
        out_dir = os.path.join(rc.ROOT, "digests", "preview", run)
        key = rc.run_key(out_dir)
        for day in sorted(key):
            for story in rc.back_stories_from_markdown(rc.run_edition(out_dir, key, day, "arcs"),
                                                       rc.run_edition(out_dir, key, day, "today"), set()):
                found = [s for f in ("hari_ini", "back") for s in cc.causal_spans(story[f])]
                if not found:
                    continue
                sources = rc.day_texts(cur, day, story["judul"]) + rc.alur_texts(cur, out_dir, day, story["judul"])
                quotes = [(w, t) for t in sources for w in rc.windows(t)]
                for claim in found:
                    best = None
                    for q, t in quotes:
                        if not cc.quotable(q):
                            continue
                        for link in cc.links(q, t)[0]:
                            if cc.supports(link, claim):
                                cost = len(missed(claim.effect, link.effect)) + len(missed(claim.cause, link.cause))
                                if best is None or cost < best[0]:
                                    best = (cost, link)
                    if best is None:
                        continue
                    link = best[1]
                    print(f"{run} {day} {claim.word!r}: {claim.sentence[:110]}")
                    print(f"   effect missed {missed(claim.effect, link.effect)}  | cause missed "
                          f"{missed(claim.cause, link.cause)}")
                    print(f"   link: {link.sentence[:160]}")


if __name__ == "__main__":
    main()
