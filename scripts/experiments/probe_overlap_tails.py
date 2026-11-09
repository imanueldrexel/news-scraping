"""SYS-142: how many stored L2 rows are the tail window of a split paragraph that adds fewer than
CHUNK_OVERLAP_TOKENS new words. Read-only.

The chunker splits a paragraph longer than CHUNK_MAX_TOKENS into windows that step by
max - overlap, and keeps whatever remains as the last one: 81 words -> [80, 21], 1 new word. Such a
tail starts with the previous window's last `overlap` words, so it is found exactly: a row whose
first `overlap` words equal the previous row's last `overlap` words, with fewer than
2 * overlap words in all (fewer than `overlap` new ones).

    venv\\Scripts\\python.exe scripts\\experiments\\probe_overlap_tails.py
"""
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import CHUNK_OVERLAP_TOKENS  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

OVERLAP = CHUNK_OVERLAP_TOKENS
CANDIDATES_SQL = text("""
    SELECT cur.sitemap_id, cur.token_count, cur.text_content AS cur, prev.text_content AS prev,
           (a.sitemap_id IS NOT NULL) AS has_article
    FROM chunks cur
    JOIN chunks prev ON prev.sitemap_id = cur.sitemap_id AND prev.chunk_level = 2
                    AND prev.chunk_index = cur.chunk_index - 1
    LEFT JOIN articles a ON a.sitemap_id = cur.sitemap_id
    WHERE cur.chunk_level = 2 AND cur.chunk_index > 0 AND cur.token_count < :limit
""")


def is_overlap_tail(cur: str, prev: str) -> bool:
    c, p = cur.split(), prev.split()
    return len(c) >= OVERLAP and len(p) >= OVERLAP and c[:OVERLAP] == p[-OVERLAP:]


if __name__ == "__main__":
    with SQLAlchemyClient().get_session() as s:
        print("database:", s.execute(text("SELECT current_database()")).scalar(), " overlap =", OVERLAP)
        total = s.execute(text("SELECT count(*) FROM chunks WHERE chunk_level = 2")).scalar()
        on_articles = s.execute(text(
            "SELECT count(*) FROM chunks c JOIN articles a USING (sitemap_id) WHERE c.chunk_level = 2")).scalar()
        rows = s.execute(CANDIDATES_SQL, {"limit": 2 * OVERLAP}).fetchall()
    tails = [r for r in rows if is_overlap_tail(r.cur, r.prev)]
    served = [r for r in tails if r.has_article]
    new_words = Counter(min(r.token_count - OVERLAP, OVERLAP) for r in served)
    buckets = {"1-5": sum(n for k, n in new_words.items() if 1 <= k <= 5),
               "6-10": sum(n for k, n in new_words.items() if 6 <= k <= 10),
               "11-19": sum(n for k, n in new_words.items() if 11 <= k <= 19)}
    print(f"L2 rows: {total:,} ({on_articles:,} on articles)")
    print(f"rows under {2 * OVERLAP} words after another row: {len(rows):,}")
    print(f"overlap tails (< {OVERLAP} new words): {len(tails):,}, of which on articles: {len(served):,} "
          f"= {len(served) / on_articles:.2%} of served L2 rows; articles affected: "
          f"{len({r.sitemap_id for r in served}):,}")
    print("new words per served tail:", buckets)
