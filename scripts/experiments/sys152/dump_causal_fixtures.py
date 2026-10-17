"""SYS-152: print what the arc model sees of the sources behind QA's six hand-checked causal sentences (read-only).

Each source's L1 opening (thread_finder.opening, ARTICLE_CHARS) is the text a `kutipan` must be found in, so the
unit fixtures in tests/unit/test_causal_check.py are copied from this output.

    venv\Scripts\python.exe scripts/experiments/sys152/dump_causal_fixtures.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

from newscrawler.core.story_summary import ARTICLE_CHARS  # noqa: E402
from newscrawler.core.thread_finder import opening  # noqa: E402

HEADLINES = ["Tiket Pesawat Mahal, Kemenhaj Bahas Ulang Biaya Haji", "Suahasil Akui Defisit APBN 2026 Bisa Melebar",
             "Menteri UMKM Ungkap Alasan Perpres Ojol Belum Terbit", "63.789 Orang Kena PHK sejak Januari-September 2026",
             "Kabut Asap Karhutla Ganggu Penerbangan di Palembang, OMC Dipindah",
             "Mantan Waketum Projo Desak Jokowi", "Usai Putusan MK soal Ijazah Gibran, PSHK FH UII"]
conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                        user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                        dbname=os.environ["POSTGRES_DB_NAME"])
conn.set_session(readonly=True)
cur = conn.cursor()
for h in HEADLINES:
    cur.execute("""SELECT s.headline, c.text_content FROM sitemaps s JOIN chunks c ON c.sitemap_id = s.sitemap_id
                   WHERE s.headline ILIKE %s AND c.chunk_level = 1 LIMIT 1""", (h + "%",))
    row = cur.fetchone()
    print("=====", row[0] if row else h)
    print(opening(row[1])[:ARTICLE_CHARS] if row else "(no L1)")
