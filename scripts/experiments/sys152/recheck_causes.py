"""SYS-152 (ADR-018): would the causal gate keep the causal sentences of the stored replays (read-only, no LLM)?

The stored arcs (arcs-v4/v5/v6) were written before the `sebab` field existed, so this asks the question the
gate will ask of the model's quote, with the best quote the model COULD have given: for every causal word in an
arc's prose, is there a window of one or two adjacent sentences in what the model saw -- that day's articles
sharing >= 2 judul words (headline + L1 text, ARTICLE_CHARS) and the arc's alur items (headline + opening,
OPENING_CHARS) -- that `causal_check.supports` accepts? "backed" means the gate can keep the sentence; "refused"
means the retry will have to drop the causal word (or the sentence was invented).

    venv\\Scripts\\python.exe scripts/experiments/sys152/recheck_causes.py
"""
import csv
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core.story_summary import ARTICLE_CHARS  # noqa: E402
from newscrawler.core.thread_finder import opening  # noqa: E402
from replay_story_arcs import back_stories_from_markdown, run_edition, run_key  # noqa: E402

RUNS = ["arcs-v4", "arcs-v5", "arcs-v6"]


def windows(text: str) -> list:
    sents = cc.sentences(text)
    return [w for w in sents + [f"{a} {b}" for a, b in zip(sents, sents[1:])] if cc.quotable(w)]


def day_texts(cur, day: str, judul: str) -> list:
    """What the model saw of that day's articles on the story, approximated as recheck_replays.day_source does."""
    words = [w.lower() for w in re.findall(r"\w{5,}", judul)]
    cur.execute("""SELECT s.headline, c.text_content FROM sitemaps s JOIN chunks c ON c.sitemap_id = s.sitemap_id
                   WHERE s.posted_at = %s AND c.chunk_level = 1""", (int(day.replace("-", "")),))
    return [f"{h}\n{(t or '')[:ARTICLE_CHARS]}" for h, t in cur.fetchall()
            if sum(w in f"{h} {(t or '')[:600]}".lower() for w in words) >= 2]


def alur_texts(cur, out_dir: str, day: str, judul: str) -> list:
    """The arc's chosen alur items (handcheck.csv rows) as the model saw them: headline + opening."""
    path = os.path.join(out_dir, "handcheck.csv")
    if not os.path.exists(path):
        return []
    heads = [r["text"] for r in csv.DictReader(open(path, encoding="utf-8"))
             if r["kind"] == "alur" and r["date"] == day and r["story"] == judul]
    out = []
    for h in heads:
        cur.execute("""SELECT s.headline, c.text_content FROM sitemaps s JOIN chunks c ON c.sitemap_id = s.sitemap_id
                       WHERE s.headline = %s AND c.chunk_level = 1 LIMIT 1""", (h,))
        row = cur.fetchone()
        if row:
            out.append(f"{row[0]}\n{opening(row[1] or '')}")
    return out


def main():
    conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                            user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                            dbname=os.environ["POSTGRES_DB_NAME"])
    conn.set_session(readonly=True)
    cur = conn.cursor()
    arcs = with_cause = spans = backed = 0
    for run in RUNS:
        out_dir = os.path.join(ROOT, "digests", "preview", run)
        key = run_key(out_dir)
        for day in sorted(key):
            stories = back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                                 run_edition(out_dir, key, day, "today"), set())
            for story in stories:
                arcs += 1
                prose = [(f, story[f]) for f in ("hari_ini", "back")]
                found = [(f, s) for f, text in prose for s in cc.causal_spans(text)]
                if not found:
                    continue
                with_cause += 1
                sources = day_texts(cur, day, story["judul"]) + alur_texts(cur, out_dir, day, story["judul"])
                quotes = [w for text in sources for w in windows(text)]
                print(f"{run} {day} | {story['judul'][:70]} | {len(sources)} sources")
                for field, span in found:
                    ok = any(cc.supports(q, span) for q in quotes)
                    spans += 1
                    backed += ok
                    print(f"   {'backed ' if ok else 'REFUSED'} {field:8} {span.word!r}: {span.sentence[:150]}")
    print(f"\narcs {arcs}; arcs with a causal word {with_cause}; causal words {spans}; "
          f"backed {backed}; refused {spans - backed}")


if __name__ == "__main__":
    main()
