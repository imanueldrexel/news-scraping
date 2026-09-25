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
    ChunksTable,
    NewsArticlesTable,
    SitemapTable,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import (
    SQLAlchemyClient,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyArticleDataSource:
    # OPS-07 (#55): `crawl_log` is the pipeline's only non-silent failure record
    # -- CLAUDE.md's rule is "process_event catches BaseException and logs at
    # INFO, so check crawl_log instead". A failure to WRITE it was logged at
    # DEBUG, below the INFO level this module sets, so the safety net was itself
    # silent when it broke and the runbook read the absent row as "the scheduler
    # did not fire". These stay non-raising -- a logging failure must not abort a
    # crawl -- but they are WARNINGs now, and the disabled state is stated once
    # at the top of the log rather than inferred from a missing row.
    _crawl_log_disabled_warned = False

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
            log_id = row.log_id if row else None
            if log_id is None:
                self._warn_crawl_log_disabled("INSERT returned no log_id")
            return log_id
        except Exception as e:
            logger.warning(f"crawl_log INSERT failed for {website}/{task}: {type(e).__name__}: {e}")
            self._warn_crawl_log_disabled(f"{type(e).__name__}: {e}")
            return None

    @classmethod
    def _warn_crawl_log_disabled(cls, reason: str) -> None:
        """OPS-07: say it once, at the top of the log, instead of leaving the
        operator to infer it from an absent row. Class-level so a run that
        builds several datasources still states it once."""
        if not cls._crawl_log_disabled_warned:
            cls._crawl_log_disabled_warned = True
            logger.warning(
                "crawl_log disabled for this run: %s -- this run will leave NO crawl_log row, "
                "which is not the same as the scheduler failing to fire (OPS-07)", reason)

    def log_crawl_complete(self, log_id: Optional[int], article_count: int = 0, note: Optional[str] = None) -> None:
        """OPS-16 (#87): `note` records a verdict about a run that still
        completed -- today only the source-wide fetch-failure summary. It lands in
        `error_msg` with `status='completed'`, so the runbook can tell a run that
        fetched nothing because the source was down from one that fetched 1,000
        pages and filtered them all out. Those two rows used to be identical."""
        if not log_id:
            return
        sql = text("""
            UPDATE crawl_log
            SET status = 'completed', article_count = :count, finished_at = NOW(),
                error_msg = COALESCE(:note, error_msg)
            WHERE log_id = :log_id
        """)
        try:
            with self.client.get_session() as session:
                session.execute(sql, {"count": article_count, "log_id": log_id,
                                      "note": note[:1000] if note else None})
                session.commit()
        except Exception as e:
            logger.warning(f"crawl_log completion update failed for log_id={log_id}: {type(e).__name__}: {e}")

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
            logger.warning(f"crawl_log failure update failed for log_id={log_id}: {type(e).__name__}: {e}")

    # ── Article persistence ───────────────────────────────────────────────────

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]) -> List[int]:
        # DBT-07: a re-crawl of a sitemap that already has an article row must not
        # create a duplicate -- upsert on the unique sitemap_id index instead of a
        # plain insert.
        #
        # SYS-04: return the sitemap_ids that were *actually committed*, not the
        # sitemap_ids handed in. A row that raises inside its savepoint never
        # persists; a row that hits on_conflict_do_nothing (the sitemap already has
        # an article) persists nothing new either. Callers (crawl_log.article_count,
        # the 'saved' crawl_status stamp) must be driven by what landed in the
        # table, or both can report rows that were never written.
        committed_sitemap_ids: List[int] = []
        skipped_existing = 0
        with self.client.get_session() as session:
            for newsdetail in newsdetails:
                try:
                    # SYS-15: isolate each row in its own savepoint (matching
                    # save_sitemaps' begin_nested pattern) so a bad row rolls back
                    # only itself instead of aborting the whole session's
                    # transaction -- without this, one FK/constraint error here
                    # poisons the transaction and every later row's execute()
                    # (and the final commit) silently no-ops instead of persisting.
                    with session.begin_nested():
                        stmt = pg_insert(NewsArticlesTable).values(
                            sitemap_id=newsdetail.sitemap_id,
                            # SYS-18: extracted_text is a List[str] of paragraphs but
                            # the column is `text`; binding the list directly lets
                            # psycopg2 adapt it as a Postgres array literal
                            # (`{"para1","para2"}`), not prose. Join it the same way
                            # the trafilatura fallback's output is split back apart
                            # (crawler.py: `text.split("\n\n")`), so this round-trips.
                            extracted_text="\n\n".join(
                                p.strip() for p in (newsdetail.extracted_text or []) if p and p.strip()
                            ),
                            writer=newsdetail.reporter,
                            meta_data=newsdetail.meta_data,
                            is_embedded=newsdetail.is_embedded,
                            # SYS-37: the probe's topic; None for a caller that predates it.
                            topic=getattr(newsdetail, "topic", None),
                            topic_confidence=getattr(newsdetail, "topic_confidence", None),
                            knowledge_extracted=0,
                            knowledge_extracted_at=None,
                        ).on_conflict_do_nothing(
                            index_elements=[NewsArticlesTable.sitemap_id]
                        ).returning(NewsArticlesTable.sitemap_id)
                        # RETURNING gives back a row only when the INSERT actually
                        # happened; on_conflict_do_nothing skips it silently, which
                        # is how a real insert is told apart from a no-op skip.
                        row = session.execute(stmt).fetchone()
                        if row is not None:
                            committed_sitemap_ids.append(row.sitemap_id)
                        else:
                            skipped_existing += 1
                except BaseException as e:
                    logger.error(
                        f"Failed to add sitemap: {newsdetail}\nException: {e}"
                    )

            # DBT-11 (#46): chunks are saved before the article row exists, so
            # chunks.article_id was never written. Link them now that the
            # articles row is in this transaction -- one UPDATE for the batch.
            if committed_sitemap_ids:
                session.execute(
                    text(
                        f"UPDATE {ChunksTable.__tablename__} c "
                        f"SET {ChunksTable.article_id.name} = a.{NewsArticlesTable.articles_id.name} "
                        f"FROM {NewsArticlesTable.__tablename__} a "
                        f"WHERE c.{ChunksTable.sitemap_id.name} = a.{NewsArticlesTable.sitemap_id.name} "
                        f"AND c.{ChunksTable.article_id.name} IS NULL "
                        f"AND c.{ChunksTable.sitemap_id.name} = ANY(:ids)"
                    ),
                    {"ids": committed_sitemap_ids},
                )
            session.commit()

        if skipped_existing:
            logger.info(
                f"save_newsdetails: {skipped_existing} row(s) already had an "
                "article (on_conflict_do_nothing no-op) -- not counted as newly saved"
            )
        return committed_sitemap_ids
