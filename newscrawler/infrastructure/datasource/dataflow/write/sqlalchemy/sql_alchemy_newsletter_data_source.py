import logging
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import text

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyNewsletterDataSource:
    def __init__(self, client: SQLAlchemyClient):
        self.client = client

    def get_articles_for_date(self, date_int: int) -> List[dict]:
        """
        Returns articles published on date_int (YYYYMMDD) that have been embedded,
        joined with their L1 chunk text.
        """
        sql = text("""
            SELECT s.sitemap_id, s.headline, s.sources, s.category,
                   s.link, s.posted_at,
                   c.text_content AS l1_text
            FROM sitemaps s
            JOIN articles a ON a.sitemap_id = s.sitemap_id
            JOIN chunks   c ON c.sitemap_id = s.sitemap_id AND c.chunk_level = 1
            WHERE s.posted_at = :date_int
            ORDER BY s.sitemap_id
        """)
        with self.client.get_session() as session:
            rows = session.execute(sql, {"date_int": date_int}).fetchall()

        return [
            {
                "sitemap_id": row.sitemap_id,
                "headline":   row.headline or "",
                "source":     row.sources  or "",
                "category":   row.category or "",
                "link":       row.link     or "",
                "posted_at":  row.posted_at,
                "l1_text":    row.l1_text  or "",
            }
            for row in rows
        ]

    def save_digest(
        self,
        digest_date: date,
        file_path: str,
        cluster_count: int,
        article_count: int,
        categories: dict,
        source_ids: list,
        generation_ms: int,
    ) -> int:
        # SYS-23: SQLAlchemy's text() does not recognize ":name" as a bind param
        # when immediately followed by "::" (the Postgres cast operator) -- it left
        # ":categories::jsonb"/":source_ids::jsonb" as literal, unsubstituted SQL
        # text, so this INSERT was never syntactically valid and task=newsletter
        # has never completed. CAST(:name AS jsonb) has no such ambiguity.
        sql = text("""
            INSERT INTO newsletter_digests
                (digest_date, file_path, cluster_count, article_count,
                 categories, source_ids, generated_at, generation_ms)
            VALUES
                (:digest_date, :file_path, :cluster_count, :article_count,
                 CAST(:categories AS jsonb), CAST(:source_ids AS jsonb), NOW(), :generation_ms)
            ON CONFLICT (digest_date) DO UPDATE SET
                file_path     = EXCLUDED.file_path,
                cluster_count = EXCLUDED.cluster_count,
                article_count = EXCLUDED.article_count,
                categories    = EXCLUDED.categories,
                source_ids    = EXCLUDED.source_ids,
                generated_at  = NOW(),
                generation_ms = EXCLUDED.generation_ms
            RETURNING digest_id
        """)
        import json
        with self.client.get_session() as session:
            row = session.execute(sql, {
                "digest_date":   digest_date,
                "file_path":     file_path,
                "cluster_count": cluster_count,
                "article_count": article_count,
                "categories":    json.dumps(categories),
                "source_ids":    json.dumps(source_ids),
                "generation_ms": generation_ms,
            }).fetchone()
            session.commit()
        return row.digest_id

    # OPS-05 (4): one metric's query and its (key, needs str()) pairing. Queried
    # independently -- a single missing/broken table (e.g. newsletter_digests
    # before its migration was applied, ~4 months undetected) used to blank all
    # seven numbers via one statement of correlated sub-selects in a single
    # try/except returning {}. Now every other metric still comes through.
    _STATS_QUERIES = {
        "total_articles":    ("SELECT COUNT(*) FROM articles", False),
        "total_chunks":      ("SELECT COUNT(*) FROM chunks", False),
        "total_entities":    ("SELECT COUNT(*) FROM entities", False),
        "min_date":          ("SELECT MIN(posted_at) FROM sitemaps", True),
        "max_date":          ("SELECT MAX(posted_at) FROM sitemaps", True),
        "digests_generated": ("SELECT COUNT(*) FROM newsletter_digests", False),
        "last_crawl":        ("SELECT MAX(started_at) FROM crawl_log WHERE status = 'completed'", True),
    }

    def get_stats(self) -> dict:
        stats = {}
        for key, (sql_text, stringify) in self._STATS_QUERIES.items():
            try:
                with self.client.get_session() as session:
                    value = session.execute(text(sql_text)).scalar()
            except Exception as e:
                logger.warning(f"Stats query for '{key}' failed: {e}")
                value = None
            stats[key] = str(value) if (stringify and value is not None) else value
        return stats
