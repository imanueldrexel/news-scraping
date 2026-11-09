"""SYS-186 (#387) offline (no LLM): every "hingga / sampai <time>" end point in the stored arcs, and whether a source
states it as an end (`source_check.unbacked_end_times`).

Reads the v4/v5/v6 arc editions through their key.json, and, read-only from the DB, the day's articles on each story
(`recheck_replays.day_source`: >= 2 judul words) and the arc's alur items (`recheck_causes.alur_texts`).

    venv\\Scripts\\python.exe scripts\\experiments\\sys186\\recheck_end_times.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments", "sys152"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments", "sys169_170"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core import source_check as sc  # noqa: E402
from recheck_causes import alur_texts  # noqa: E402
from recheck_replays import RUNS, day_source  # noqa: E402
from replay_story_arcs import back_stories_from_markdown, run_edition, run_key  # noqa: E402


def main():
    conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                            user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                            dbname=os.environ["POSTGRES_DB_NAME"])
    conn.set_session(readonly=True)
    cur = conn.cursor()
    arcs = found = refused = 0
    for run in RUNS:
        out_dir = os.path.join(ROOT, "digests", "preview", run)
        key = run_key(out_dir)
        for day in sorted(key):
            stories = back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                                 run_edition(out_dir, key, day, "today"), set())
            for story in stories:
                arcs += 1
                prose = f"{story['hari_ini']}\n{story['back']}"
                points = sc.end_points(prose)
                if not points:
                    continue
                _, source = day_source(cur, day, story["judul"])
                source = "\n\n".join([source] + alur_texts(cur, out_dir, day, story["judul"]))
                bad = set(sc.unbacked_end_times(prose, source))
                found += len(points)
                refused += len(bad)
                for phrase, _ in points:
                    print(f"{run} {day} | {story['judul'][:60]} | {'REFUSED' if phrase in bad else 'backed '} {phrase!r}")
    print(f"\narcs {arcs}; end points {found}; refused {refused}")


if __name__ == "__main__":
    main()
