"""SYS-169/170 offline (no LLM): the future times and change claims in the v4/v5/v6 arcs, old rule vs new,
and (SYS-174) every relative phrase whose span still runs past the edition day.

Reads each run's arcs edition through its key.json (`replay_story_arcs.back_stories_from_markdown`) and
prints, per arc, every future time (`source_check.future_phrases`) and change claim (`_CHANGE_CLAIM`).
With --db it also looks up, read-only, the day's articles that state each future time, so the verdict
(stated by today's articles or not) can be checked by hand against the story's own articles.

A running span is judged with `story_arc.unbacked_times` as the latar (the stored back paragraph joins latar
and agenda), against the arc's timeline items (its run's handcheck.csv) and, with --db, the dates the day's
articles state. Without --db the verdict may refuse a phrase an article's date backs.

    venv\Scripts\python.exe scripts\experiments\sys169_170\recheck_replays.py [--db]
"""
import csv
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))

from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core import story_arc as sa  # noqa: E402
from replay_story_arcs import back_stories_from_markdown, run_edition, run_key  # noqa: E402

OLD_CHANGE = re.compile(rf"\b(?:{sc._CHANGE_VERBS})\b(?:\s+\S+){{0,8}}?\s+(?:men)?jadi\s+"
                        r"(?:(?:sekitar|sebesar|sebanyak|hampir|lebih\s+dari|lebih\s+kurang)\s+)?"
                        r"(?:Rp|US\$|\$)?\s?(?P<number>\d+(?:[.,]\d+)*)", re.IGNORECASE)
RUNS = ["arcs-v4", "arcs-v5", "arcs-v6"]


def item_days(out_dir: str) -> dict:
    """(edition day, arc judul) -> its timeline items' days, from the run's handcheck.csv."""
    days = {}
    with open(os.path.join(out_dir, "handcheck.csv"), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["kind"] == "alur" and row["item_date"]:
                days.setdefault((row["date"], row["story"]), set()).add(date.fromisoformat(row["item_date"]))
    return days


def day_source(cur, day: str, judul: str) -> tuple:
    """A story's sources, approximated: the day's articles sharing >= 2 judul words (count, joined text)."""
    words = [w.lower() for w in re.findall(r"\w{5,}", judul)]
    cur.execute("""SELECT s.headline, a.extracted_text FROM sitemaps s
                   JOIN articles a ON a.sitemap_id = s.sitemap_id WHERE s.posted_at = %s""",
                (int(day.replace("-", "")),))
    rows = [(h, t) for h, t in cur.fetchall() if sum(w in f"{h} {t[:600]}".lower() for w in words) >= 2]
    return len(rows), "\n\n".join(f"{h}\n{t}" for h, t in rows)


def main():
    use_db = "--db" in sys.argv
    cur = None
    if use_db:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        import psycopg2
        conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                                user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                                dbname=os.environ["POSTGRES_DB_NAME"])
        conn.set_session(readonly=True)
        cur = conn.cursor()
    arcs = futures = claims_old = claims_new = spans_running = spans_refused = 0
    for run in RUNS:
        out_dir = os.path.join(ROOT, "digests", "preview", run)
        key, items = run_key(out_dir), item_days(out_dir)
        for day in sorted(key):
            stories = back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                                 run_edition(out_dir, key, day, "today"), set())
            for story in stories:
                arcs += 1
                prose = f"{story['hari_ini']}\n{story['back']}"
                edition = date.fromisoformat(day)
                # SYS-174/177: a span still running (or ending today) is judged by its field: the hari_ini as today's
                # news (`present`), the back paragraph (latar + agenda) as the latar, with its future-verb cue.
                for field, text in (("hari_ini", story["hari_ini"]), ("back", story["back"])):
                    running = [p for p, first, last in sc.relative_times(text, edition) if last >= edition]
                    spans_running += len(running)
                    if not running:
                        continue
                    known = {edition} | items.get((day, story["judul"]), set())
                    if cur:
                        known |= {sc.resolve(d, m, edition) for d, m in sc.dates_in(day_source(cur, day, story["judul"])[1])}
                    refused = sa.unbacked_times(text, edition, known - {None}, "", present=field == "hari_ini")
                    for phrase in running:
                        verdict = "REFUSED" if phrase in refused else "backed"
                        spans_refused += verdict == "REFUSED"
                        print(f"{run} {day} | running span {phrase!r} ({field}): {verdict} | {story['judul'][:70]}")
                fut = sc.future_phrases(prose)
                old = [m.group(0) for s in sc._sentences(prose) for m in OLD_CHANGE.finditer(s)]
                new = [m.group(0) for s in sc._sentences(prose) for m in sc._CHANGE_CLAIM.finditer(s)]
                futures += len(fut)
                claims_old += len(old)
                claims_new += len(new)
                if not (fut or old or new):
                    continue
                print(f"{run} {day} | {story['judul'][:70]}")
                for _, phrase in fut:
                    sentence = next(s for s in sc._sentences(prose) if phrase in s)
                    print(f"   future  {phrase!r}: {sentence[:160]}")
                    if cur:
                        cur.execute("""SELECT s.headline FROM sitemaps s JOIN articles a ON a.sitemap_id = s.sitemap_id
                                       WHERE s.posted_at = %s AND a.extracted_text ~* %s LIMIT 400""",
                                    (int(day.replace("-", "")), r"\m" + phrase.replace(" ", r"\s+") + r"\M"))
                        words = set(w.lower() for w in re.findall(r"\w{5,}", story["judul"]))
                        hits = [h for (h,) in cur.fetchall() if len(words & set(re.findall(r"\w{5,}", h.lower()))) >= 2]
                        print(f"            articles that day stating it, sharing >= 2 judul words: {len(hits)}")
                        for h in hits[:4]:
                            print(f"              - {h[:110]}")
                for c in sorted(set(old) | set(new)):
                    print(f"   change  {c!r}  old={'Y' if c in old else '-'} new={'Y' if c in new else '-'}")
                    if cur and c in new and c not in old:
                        n, source = day_source(cur, day, story["judul"])
                        verdict = "REFUSED" if sc.unbacked_changes(c, source) else "backed"
                        print(f"            new claim vs {n} articles of the day: {verdict}")
    print(f"\narcs {arcs}; future times {futures}; change claims old {claims_old} -> new {claims_new}; "
          f"running spans {spans_running} ({spans_refused} refused by SYS-174/177)")


if __name__ == "__main__":
    main()
