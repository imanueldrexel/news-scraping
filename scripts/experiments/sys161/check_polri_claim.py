"""SYS-161 offline: the v5 10-11 Polri latar against every stored 10-11 Polri-mutation article (read-only)."""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))
sys.path.insert(0, os.getcwd())
import psycopg2  # noqa: E402

from newscrawler.core import source_check as sc  # noqa: E402

LATAR = ("Mutasi ini merupakan gelombang berikutnya setelah Kapolri Jenderal Suyudi Ario Seto lebih dulu merotasi "
         "19 jabatan Kapolda beberapa hari setelah dilantik. Sebelumnya, pada awal Oktober, Polri memutasi 88 perwira "
         "tinggi dan perwira menengah, termasuk 19 Kapolda, melalui Surat Telegram Nomor ST/2205/X/KEP./2026 "
         "tertanggal 2 Oktober 2026. Kini jumlah personel yang dimutasi bertambah menjadi 199 orang.")

conn = psycopg2.connect(host=os.environ["POSTGRES_DB_HOST"], port=os.environ["POSTGRES_DB_PORT"],
                        user=os.environ["POSTGRES_DB_USER"], password=os.environ["POSTGRES_DB_PASS"],
                        dbname=os.environ["POSTGRES_DB_NAME"])
conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("""SELECT s.headline, a.extracted_text FROM sitemaps s JOIN articles a ON a.sitemap_id = s.sitemap_id
               WHERE s.posted_at IN (20261010, 20261011) AND a.extracted_text ~ '\\m199\\M'
                 AND (s.headline ~* 'polri|kapolri|mutasi|rotasi|rombak' )""")
rows = cur.fetchall()
print("articles:", len(rows))
for h, _ in rows:
    print("  -", h[:110])
source = "\n\n".join(f"{h}\n{t}" for h, t in rows)
print("claims refused (all articles joined):", sc.unbacked_changes(LATAR, source))
passing = [h for h, t in rows if not sc.unbacked_changes(LATAR, f"{h}\n{t}")]
print("single articles that would back it:", passing)
