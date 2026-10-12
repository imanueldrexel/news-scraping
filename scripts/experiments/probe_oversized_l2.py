"""SYS-137: L2 chunk rows longer than CHUNK_MAX_TOKENS words, split by what owns them. Read-only.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_oversized_l2.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import CHUNK_MAX_TOKENS  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

SQL = """
SELECT s.sources,
       (a.sitemap_id IS NOT NULL) AS has_article,
       s.crawl_status,
       COUNT(DISTINCT c.sitemap_id) AS sitemaps,
       COUNT(*) AS l2_rows,
       MAX(c.token_count) AS max_words,
       MIN(c.created_at)::date AS first_created,
       MAX(c.created_at)::date AS last_created,
       COUNT(*) FILTER (WHERE c.embedding_id IS NULL) AS no_vector
FROM chunks c
JOIN sitemaps s ON s.sitemap_id = c.sitemap_id
LEFT JOIN articles a ON a.sitemap_id = c.sitemap_id
WHERE c.chunk_level = 2 AND c.token_count > :m
GROUP BY 1, 2, 3
ORDER BY 1, 2 DESC, 3
"""

if __name__ == "__main__":
    with SQLAlchemyClient().get_session() as s:
        print("database:", s.execute(text("SELECT current_database()")).scalar(), " CHUNK_MAX_TOKENS =", CHUNK_MAX_TOKENS)
        rows = s.execute(text(SQL), {"m": CHUNK_MAX_TOKENS}).fetchall()
        print("%-12s %-8s %-16s %8s %8s %6s %11s %11s %8s" % ("source", "article", "crawl_status", "sitemaps",
                                                              "l2_rows", "max_w", "first", "last", "no_vec"))
        for r in rows:
            print("%-12s %-8s %-16s %8d %8d %6d %11s %11s %8d" % (r.sources, r.has_article, r.crawl_status,
                                                                 r.sitemaps, r.l2_rows, r.max_words,
                                                                 r.first_created, r.last_created, r.no_vector))
        mentions = s.execute(text(
            "SELECT COUNT(*) FROM entity_mentions m JOIN chunks c ON c.chunk_id = m.chunk_id "
            "LEFT JOIN articles a ON a.sitemap_id = c.sitemap_id "
            "WHERE c.chunk_level = 2 AND c.token_count > :m AND a.sitemap_id IS NULL"), {"m": CHUNK_MAX_TOKENS}).scalar()
        print("entity mentions on oversized L2 rows of sitemaps without an article:", mentions)
