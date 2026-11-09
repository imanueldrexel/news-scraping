"""ADR-020 / SYS-186..193: does any of the arc guards raise on real article text? (read-only, no LLM)

`story_arc.parse` lets only `Rejected` through `ask_json`; any other exception from a guard stops the whole edition.
This runs every pure guard on the L1 text of one day's articles, as prose and as source, and reports exceptions.

    venv\\Scripts\\python.exe scripts/experiments/sys188/fuzz_gate_on_corpus.py 2026-10-17
"""
import os
import sys
import traceback
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core import causal_check as cc  # noqa: E402
from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core import story_arc as sa  # noqa: E402


def main(day: str):
    today = date.fromisoformat(day)
    conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                            user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                            dbname=os.environ["POSTGRES_DB_NAME"])
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute("""SELECT s.headline, c.text_content FROM sitemaps s JOIN chunks c ON c.sitemap_id = s.sitemap_id
                   WHERE s.posted_at = %s AND c.chunk_level = 1""", (int(day.replace("-", "")),))
    texts = [f"{h}\n{t or ''}" for h, t in cur.fetchall()]
    checks = {
        "causal_spans": lambda t: cc.causal_spans(t),
        "links+supports": lambda t: [cc.supports(link, claim) for s in cc.sentences(t)[:12]
                                     for link in cc.links(s, t)[0] for claim in cc.causal_spans(s)],
        "unbacked_end_times": lambda t: sc.unbacked_end_times(t, t),
        "future_periods": lambda t: sc.future_periods(t, today),
        "stated_periods": lambda t: sc.stated_periods(t, today),
        "unstated_periods": lambda t: [sa.unstated_periods(t, today, t, f) for f in ("agenda", "hari_ini", "latar")],
        "unbacked_times": lambda t: sa.unbacked_times(t, today, {today}, t),
        "unbacked_changes": lambda t: sc.unbacked_changes(t, t),
    }
    calls = errors = 0
    for text in texts:
        for name, check in checks.items():
            calls += 1
            try:
                check(text)
            except Exception:
                errors += 1
                if errors <= 10:
                    print(f"ERROR {name}: {text[:100]!r}\n{traceback.format_exc()}")
    print(f"{day}: {len(texts)} articles, {calls} guard calls, {errors} exceptions")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-10-17")
