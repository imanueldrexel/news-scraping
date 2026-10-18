"""SYS-190 (#391) offline (no LLM): every whole month, semester/quarter and year part in the stored arcs, and whether
today's articles state it (`story_arc.unstated_periods`).

The stored arc editions close the latar with the agenda (one "back" paragraph), so the back paragraph is judged twice:
as the latar (under SYS-177's cue) and, as an upper bound, as if all of it were the agenda. hari_ini is a present
field. Today's articles are approximated as in `recheck_replays.day_source` (>= 2 judul words).

    venv\\Scripts\\python.exe scripts\\experiments\\sys190\\recheck_periods.py
"""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments", "sys169_170"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core import story_arc as sa  # noqa: E402
from recheck_replays import RUNS, day_source  # noqa: E402
from replay_story_arcs import back_stories_from_markdown, run_edition, run_key  # noqa: E402


def main():
    conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                            user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                            dbname=os.environ["POSTGRES_DB_NAME"])
    conn.set_session(readonly=True)
    cur = conn.cursor()
    totals = {"periods": 0, "hari_ini": 0, "latar": 0, "as_agenda": 0}
    for run in RUNS:
        out_dir = os.path.join(ROOT, "digests", "preview", run)
        key = run_key(out_dir)
        for day in sorted(key):
            today = date.fromisoformat(day)
            for story in back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                                    run_edition(out_dir, key, day, "today"), set()):
                found = [(f, p) for f in ("hari_ini", "back") for p in sc.future_periods(story[f], today)]
                if not found:
                    continue
                _, stated = day_source(cur, day, story["judul"])
                refused = {"hari_ini": sa.unstated_periods(story["hari_ini"], today, stated, "hari_ini"),
                           "latar": sa.unstated_periods(story["back"], today, stated, "latar"),
                           "as_agenda": sa.unstated_periods(story["back"], today, stated, "agenda")}
                totals["periods"] += len(found)
                for name, phrases in refused.items():
                    totals[name] += len(phrases)
                for field, (_, _, phrase, _, last) in found:
                    marks = [name for name, phrases in refused.items() if phrase in phrases
                             and (name == "hari_ini") == (field == "hari_ini")]
                    print(f"{run} {day} | {story['judul'][:55]} | {field:8} {phrase!r} (to {last}) "
                          f"{'REFUSED as ' + '/'.join(marks) if marks else 'backed or not judged'}")
    print(f"\n{totals}")


if __name__ == "__main__":
    main()
