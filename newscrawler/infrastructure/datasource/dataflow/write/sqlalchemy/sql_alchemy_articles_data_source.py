from sqlalchemy import text
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import (
    NewsArticlesTable,
    SitemapTable,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import (
    SQLAlchemyClient,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyArticleDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.client = sql_alchemy_client

    # ── Crawl logging (Phase 5) ───────────────────────────────────────────────

    def log_crawl_start(self, website: str, task: str) -> Optional[int]:
        sql = text("""
            INSERT INTO crawl_log (website, task, status, started_at)
            VALUES (:website, :task, 'started', NOW())
            RETURNING log_id
        """)
        try:
            with self.client.get_session() as session:
                row = session.execute(sql, {"website": website, "task": task}).fetchone()
                session.commit()
            return row.log_id if row else None
        except Exception as e:
            logger.debug(f"crawl_log not available yet: {e}")
            return None

    def log_crawl_complete(self, log_id: Optional[int], article_count: int = 0) -> None:
        if not log_id:
            return
        sql = text("""
            UPDATE crawl_log
            SET status = 'completed', article_count = :count, finished_at = NOW()
            WHERE log_id = :log_id
        """)
        try:
            with self.client.get_session() as session:
                session.execute(sql, {"count": article_count, "log_id": log_id})
                session.commit()
        except Exception as e:
            logger.debug(f"crawl_log update failed: {e}")

    def log_crawl_failed(self, log_id: Optional[int], error_msg: str) -> None:
        if not log_id:
            return
        sql = text("""
            UPDATE crawl_log
            SET status = 'failed', error_msg = :msg, finished_at = NOW()
            WHERE log_id = :log_id
        """)
        try:
            with self.client.get_session() as session:
                session.execute(sql, {"msg": error_msg[:1000], "log_id": log_id})
                session.commit()
        except Exception as e:
            logger.debug(f"crawl_log failed-update failed: {e}")

    # ── Article persistence ───────────────────────────────────────────────────

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]):
        # DBT-07: a re-crawl of a sitemap that already has an article row must not
        # create a duplicate -- upsert on the unique sitemap_id index instead of a
        # plain insert.
        with self.client.get_session() as session:
            for newsdetail in newsdetails:
                try:
                    stmt = pg_insert(NewsArticlesTable).values(
                        sitemap_id=newsdetail.sitemap_id,
                        extracted_text=newsdetail.extracted_text,
                        writer=newsdetail.reporter,
                        meta_data=newsdetail.meta_data,
                        is_embedded=newsdetail.is_embedded,
                        knowledge_extracted=0,
                        knowledge_extracted_at=None,
                    ).on_conflict_do_nothing(index_elements=[NewsArticlesTable.sitemap_id])
                    session.execute(stmt)
                except BaseException as e:
                    logger.error(
                        f"Failed to add sitemap: {newsdetail}\nException: {e}"
                    )

            session.commit()
