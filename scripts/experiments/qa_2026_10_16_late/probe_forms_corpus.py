"""QA 2026-10-16 (late): corpus counts (read-only) of the forms the SYS-171/174/175/176 fixes leave out.

Each row: articles whose extracted text matches the POSIX regex, plus 3 sample snippets.

    venv\Scripts\python.exe scripts/experiments/qa_2026_10_16_late/probe_forms_corpus.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
import psycopg2  # noqa: E402

FUT = r"(akan|dijadwalkan|ditargetkan|direncanakan|rencananya|menyusul|bakal|digelar|berlaku|rampung)"
DAY = r"(senin|selasa|rabu|kamis|jumat|sabtu|minggu)"
ADV = r"(lagi|kembali|tajam|signifikan|drastis|pesat|cukup|sangat|terus)"
VERB = r"(bertambah|naik|meningkat|turun|berkurang|menurun|melonjak|anjlok|melemah|menguat|membengkak)"
FORMS = [
    ("future verb + bare 'akhir pekan' (no ini/lalu/depan)", rf"\m{FUT}(\s+\S+){{0,3}}\s+akhir\s+pekan\M(?!\s+(ini|lalu|depan|mendatang|kemarin))"),
    ("future verb + bare 'akhir tahun' (no ini/lalu/depan/YYYY)", rf"\m{FUT}(\s+\S+){{0,3}}\s+akhir\s+tahun\M(?!\s+(ini|lalu|depan|mendatang|kemarin|\d))"),
    ("future verb + bare 'pertengahan/awal tahun'", rf"\m{FUT}(\s+\S+){{0,3}}\s+(pertengahan|awal)\s+tahun\M(?!\s+(ini|lalu|depan|mendatang|kemarin|\d))"),
    ("'<hari>, pekan/minggu depan' (comma)", rf"\m{DAY},\s+(pekan|minggu)\s+(depan|mendatang)\M"),
    ("'<hari> pekan/minggu depan' (no comma)", rf"\m{DAY}\s+(pekan|minggu)\s+(depan|mendatang)\M"),
    ("'(awal|pertengahan) pekan depan'", r"\m(awal|pertengahan)\s+(pekan|minggu)\s+(depan|mendatang)\M"),
    ("'<verb> <adverb> mencapai N'", rf"\m{VERB}\s+{ADV}\s+mencapai\s+(rp\s?)?\d"),
    ("'<verb> mencapai N' (adjacent)", rf"\m{VERB},?\s+mencapai\s+(rp\s?)?\d"),
    ("'<verb> <N%> mencapai N'", rf"\m{VERB}\s+(sebesar\s+)?\d+([.,]\d+)?\s*(%|persen)\s+(menjadi\s+)?mencapai\s+(rp\s?)?\d"),
    ("'hingga/sampai/per <hari> <pagi..malam> (d/m'", rf"\m(hingga|sampai|per)\s+(hari\s+)?{DAY}\s+(pagi|siang|sore|malam|dini\s+hari)\s*\(?\d{{1,2}}/\d"),
    ("'hingga/sampai/per <hari> (d/m'", rf"\m(hingga|sampai|per)\s+(hari\s+)?{DAY},?\s*\(?\d{{1,2}}/\d"),
]
conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                        user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                        dbname=os.environ["POSTGRES_DB_NAME"])
conn.set_session(readonly=True)
cur = conn.cursor()
only = sys.argv[1:]
for name, rx in FORMS:
    if only and not any(o in name for o in only):
        continue
    cur.execute("SELECT count(*) FROM articles WHERE extracted_text ~* %s", (rx,))
    n = cur.fetchone()[0]
    cur.execute("SELECT substring(extracted_text from %s) FROM articles WHERE extracted_text ~* %s LIMIT 4",
                (r"(?i)(.{0,70}" + rx.replace(r"\m", r"\y").replace(r"\M", r"\y") + ".{0,40})", rx))
    print(f"{n:6d}  {name}")
    for (s,) in cur.fetchall():
        print("          ", re.sub(r"\s+", " ", s or "")[:170])
