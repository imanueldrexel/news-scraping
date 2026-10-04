"""
OPS-11 (#67) Done-when, on the test DB: task=extract_knowledge with every
Gemini call failing leaves a crawl_log row with status='failed' and a non-empty
error_msg; a run with nothing to do leaves status='completed', article_count=0;
task=newsletter leaves a row too. Built on the real KnowledgeExtractor and
SQLAlchemyKnowledgeDataSource with only the Gemini call itself replaced, so the
crawl_log write goes through the real SQL.
"""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "OPS11TEST"


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    # get_articles_pending_extraction selects EVERY article with
    # knowledge_extracted = 0, so rows other modules seeded in this shared test
    # DB would join this run. Park them on a sentinel value for the duration
    # and restore it afterwards, so these tests see only their own articles.
    with c.get_session() as s:
        parked = [r[0] for r in s.execute(text(
            "SELECT articles_id FROM articles WHERE knowledge_extracted = 0")).fetchall()]
        if parked:
            s.execute(text("UPDATE articles SET knowledge_extracted = 9 WHERE articles_id = ANY(:ids)"), {"ids": parked})
        s.commit()
    yield c
    with c.get_session() as s:
        if parked:
            s.execute(text("UPDATE articles SET knowledge_extracted = 0 WHERE articles_id = ANY(:ids)"), {"ids": parked})
        s.commit()
    with c.get_session() as s:
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.execute(text("DELETE FROM crawl_log WHERE website = 'ALL' AND started_at > NOW() - INTERVAL '10 minutes'"))
        s.commit()


def _seed_pending_articles(client, n):
    with client.get_session() as s:
        for _ in range(n):
            sid = s.execute(
                text("INSERT INTO sitemaps (headline, link, sources, category, posted_at, crawl_status) "
                     "VALUES ('h', :l, :s, 'bisnis', 20260922, 'saved') RETURNING sitemap_id"),
                {"l": f"https://ops11.test/{uuid.uuid4().hex}", "s": SOURCE}).scalar()
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, writer, meta_data, knowledge_extracted) "
                           "VALUES (:sid, 'Bank Indonesia menaikkan suku bunga acuan.', '[]', '{}', 0)"), {"sid": sid})
        s.commit()


def _service_with_failing_gemini(client, error):
    """CrawlerServiceImpl over a repository double that owns a REAL
    SQLAlchemyKnowledgeDataSource + KnowledgeExtractor (only the
    provider replaced) and the real crawl_log writer -- without loading FAISS/e5."""
    from unittest.mock import MagicMock
    from newscrawler.core.knowledge_extractor import GeminiTransientError, KnowledgeExtractor
    from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )

    ds = SQLAlchemyKnowledgeDataSource(client)
    class Down:
        """A configured provider whose every call fails without a response."""
        name, priced = "gemini-test", False

        def complete(self, prompt):
            raise GeminiTransientError(error)
    kx = KnowledgeExtractor(ds, provider=Down(), daily_limit=1400, batch_size=50, allow_peak=True)

    articles_ds = SQLAlchemyArticleDataSource(client)
    repo = MagicMock()
    repo.extract_knowledge.side_effect = kx.extract_all
    repo.log_crawl_start.side_effect = articles_ds.log_crawl_start
    repo.log_crawl_complete.side_effect = articles_ds.log_crawl_complete
    repo.log_crawl_failed.side_effect = articles_ds.log_crawl_failed
    repo.generate_newsletter.return_value = "digests/test.md"
    svc = CrawlerServiceImpl.__new__(CrawlerServiceImpl)
    svc.data_flow_repo = repo
    return svc


def _last_row(client, task):
    with client.get_session() as s:
        return s.execute(text("SELECT website, task, status, article_count, error_msg FROM crawl_log "
                              "WHERE task = :t ORDER BY log_id DESC LIMIT 1"), {"t": task}).fetchone()


class TestExtractKnowledgeCrawlLogLive:
    def test_every_call_failing_leaves_a_failed_row_with_the_error(self, client):
        _seed_pending_articles(client, 2)
        svc = _service_with_failing_gemini(client, "ClientError: 400 API key not valid. Please pass a valid API key.")
        assert svc.extract_knowledge() == 0
        row = _last_row(client, "extract_knowledge")
        assert (row.website, row.task, row.status) == ("ALL", "extract_knowledge", "failed")
        assert "all 2 extraction calls failed" in row.error_msg and "API key not valid" in row.error_msg
        with client.get_session() as s:
            attempts = s.execute(text("SELECT COALESCE(SUM(knowledge_extract_attempts), 0) FROM articles a JOIN sitemaps s "
                                      "USING (sitemap_id) WHERE s.sources = :s"), {"s": SOURCE}).scalar()
        assert attempts == 0   # OPS-09: transient failures never count against the article

    def test_nothing_pending_is_a_completed_row_with_zero(self, client):
        svc = _service_with_failing_gemini(client, "never called")
        assert svc.extract_knowledge() == 0
        row = _last_row(client, "extract_knowledge")
        assert (row.status, row.article_count) == ("completed", 0)

    def test_newsletter_leaves_a_completed_row(self, client):
        svc = _service_with_failing_gemini(client, "unused")
        svc.generate_newsletter()
        row = _last_row(client, "newsletter")
        assert (row.website, row.status, row.article_count) == ("ALL", "completed", 1)
