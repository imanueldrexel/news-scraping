"""QA 2026-10-16 (late): how often does a day's article state a past date inside a running month-part span?

SYS-174 stops today from backing a span still running past it ("akhir bulan" from the 21st). Outside the agenda a
past day inside the span still backs it, and `parse` puts every date the day's `terkait` articles state into the
known days. This counts, per digest day D inside the span, the articles posted on D whose guard text (headline +
opening, ARTICLE_CHARS, as `story_summary.guard_text`) states a date in [span start, D-1]. Read-only.

    venv\Scripts\python.exe scripts/experiments/qa_2026_10_16_late/probe_running_span_backing.py
"""
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core.story_summary import ARTICLE_CHARS  # noqa: E402

conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                        user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                        dbname=os.environ["POSTGRES_DB_NAME"])
conn.set_session(readonly=True)
cur = conn.cursor()
# (span name, first day of the span, digest days inside it, after its first day)
CASES = [("akhir September (21-30)", date(2026, 9, 21), [date(2026, 9, d) for d in range(22, 31)]),
         ("pertengahan September (11-20)", date(2026, 9, 11), [date(2026, 9, d) for d in range(12, 21)]),
         ("pertengahan Oktober (11-20)", date(2026, 10, 11), [date(2026, 10, d) for d in range(12, 16)])]
for name, first, days in CASES:
    tot = hit = 0
    rows_out = []
    for d in days:
        cur.execute("""SELECT s.headline, a.extracted_text FROM sitemaps s JOIN articles a ON a.sitemap_id = s.sitemap_id
                       WHERE s.posted_at = %s""", (int(d.strftime("%Y%m%d")),))
        n = h = 0
        for headline, text in cur.fetchall():
            guard = f"{headline}\n{(text or '')[:ARTICLE_CHARS]}"
            stated = {sc.resolve(dd, mm, d) for dd, mm in sc.dates_in(guard)} - {None}
            n += 1
            h += any(first <= s < d for s in stated)
        tot, hit = tot + n, hit + h
        rows_out.append(f"  {d}: {h}/{n} ({100 * h / max(n, 1):.0f}%)")
    p = hit / max(tot, 1)
    print(f"{name}: {hit}/{tot} articles = {100 * p:.1f}%; P(>=1 of 2 terkait) ~ {100 * (1 - (1 - p) ** 2):.0f}%, "
          f"of 3 ~ {100 * (1 - (1 - p) ** 3):.0f}%")
    print("\n".join(rows_out))
