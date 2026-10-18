"""SYS-188 (#389): which words of each causal half does its best link NOT cover? (read-only, no LLM)

A stricter coverage rule (every name, every noun, every word) costs exactly the claims whose missed words fall in the
class it stops tolerating. For each causal word of the stored replays (arcs-v4/v5/v6) this prints the link with the
fewest misses (backed or not), its misses per half, each marked name (N), name standing on the link's OTHER side
(N!), affixed verb-like (V) or other (W).

    venv\\Scripts\\python.exe scripts/experiments/sys188/missed_words.py
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


def missed(half: str, side: str, other_side: str, sentence: str) -> list:
    """The words of `half` that ADR-020's `_covers` would not find."""
    on_side = cc._roots(side)
    room = on_side | (cc._roots(sentence) - cc._roots(other_side))
    out = []
    for w, is_name in story_words.content_words(half).items():
        r = cc._root(w)
        if not cc._weighs(w) or cc._meets(r, on_side) or (is_name and cc._meets(r, room)):
            continue
        tag = ("N!" if cc._meets(r, cc._roots(other_side)) else "N") if is_name else ("V" if r != w else "W")
        out.append(f"{w}({tag})")
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
                        for link in cc.links(q, t)[0]:
                            if link.negated != claim.negated:
                                continue
                            misses = (missed(claim.effect, link.effect, link.cause, link.sentence),
                                      missed(claim.cause, link.cause, link.effect, link.sentence))
                            cost = len(misses[0]) + len(misses[1])
                            if best is None or cost < best[0]:
                                best = (cost, link, misses, cc.supports(link, claim))
                    if best is None:
                        print(f"{run} {day} {claim.word!r}: NO LINK  {claim.sentence[:110]}")
                        continue
                    _, link, (effect_missed, cause_missed), ok = best
                    print(f"{run} {day} {claim.word!r} {'backed' if ok else 'REFUSED'}: {claim.sentence[:110]}")
                    print(f"   effect missed {effect_missed}  | cause missed {cause_missed}")
                    print(f"   link {link.word!r}: {link.sentence[:160]}")


if __name__ == "__main__":
    main()
