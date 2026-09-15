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
        sql = text("""
            INSERT INTO newsletter_digests
                (digest_date, file_path, cluster_count, article_count,
                 categories, source_ids, generated_at, generation_ms)
            VALUES
                (:digest_date, :file_path, :cluster_count, :article_count,
                 :categories::jsonb, :source_ids::jsonb, NOW(), :generation_ms)
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

    def get_stats(self) -> dict:
        sql = text("""
            SELECT
                (SELECT COUNT(*) FROM articles)              AS total_articles,
                (SELECT COUNT(*) FROM chunks)                AS total_chunks,
                (SELECT COUNT(*) FROM entities)              AS total_entities,
                (SELECT MIN(posted_at) FROM sitemaps)        AS min_date,
                (SELECT MAX(posted_at) FROM sitemaps)        AS max_date,
                (SELECT COUNT(*) FROM newsletter_digests)    AS digests_generated,
                (SELECT MAX(started_at) FROM crawl_log
                 WHERE status = 'completed')                 AS last_crawl
        """)
        try:
            with self.client.get_session() as session:
                row = session.execute(sql).fetchone()
            return {
                "total_articles":   row.total_articles,
                "total_chunks":     row.total_chunks,
                "total_entities":   row.total_entities,
                "min_date":         str(row.min_date) if row.min_date else None,
                "max_date":         str(row.max_date) if row.max_date else None,
                "digests_generated": row.digests_generated,
                "last_crawl":       str(row.last_crawl) if row.last_crawl else None,
            }
        except Exception as e:
            logger.warning(f"Stats query failed (crawl_log may not exist yet): {e}")
            return {}
