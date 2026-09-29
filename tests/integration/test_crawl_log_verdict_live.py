"""
DBT-40 (#168) against a live PostgreSQL: OPS-16's source-wide verdict must
actually land in `crawl_log.error_msg`.

OPS-16's unit tests stop at the repository mock ("log_crawl_complete was called
with note=..."), and the only integration double was a stub, so QA replaced
`error_msg = COALESCE(:note, error_msg)` with `error_msg = error_msg` and both
suites stayed green. The SQL is the one layer that can lose the value, so these
tests go through the real `SQLAlchemyArticleDataSource`, and the second class
through the real service's source-wide branch as well.
"""
from unittest.mock import MagicMock, patch

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT40TEST"
# The runbook's own query (OPERATIONS.md, "Was the last run a source-wide fetch failure?").
RUNBOOK_SQL = text(
    "SELECT website, started_at, article_count, error_msg FROM crawl_log "
    "WHERE task = 'full_text' AND error_msg LIKE 'source-wide fetch failure%' "
    "ORDER BY started_at DESC LIMIT 20"
)


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        s.execute(text("DELETE FROM crawl_log WHERE website = :w"), {"w": SOURCE})
        s.commit()


@pytest.fixture
def ds(client):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    return SQLAlchemyArticleDataSource(client)


def _row(client, log_id):
    with client.get_session() as s:
        return s.execute(text("SELECT status, article_count, error_msg FROM crawl_log WHERE log_id = :id"),
                         {"id": log_id}).fetchone()


class TestLogCrawlCompleteNote:
    def test_the_note_is_persisted_in_error_msg_with_status_completed(self, client, ds):
        note = "source-wide fetch failure: 40/40 (100%); 0 counted as per-URL, 40 spared and cooldown-stamped. " \
               "Reasons: 'HTTP 403': 40"
        log_id = ds.log_crawl_start(SOURCE, "full_text")
        ds.log_crawl_complete(log_id, 0, note=note)
        row = _row(client, log_id)
        assert (row.status, row.article_count, row.error_msg) == ("completed", 0, note)

    def test_the_runbook_query_finds_it(self, client, ds):
        log_id = ds.log_crawl_start(SOURCE, "full_text")
        ds.log_crawl_complete(log_id, 0, note="source-wide fetch failure: 25/25 (100%) DBT-40")
        with client.get_session() as s:
            hits = [r for r in s.execute(RUNBOOK_SQL).fetchall() if r.website == SOURCE]
        assert len(hits) == 1 and hits[0].error_msg.endswith("DBT-40")

    def test_no_note_leaves_error_msg_null(self, client, ds):
        log_id = ds.log_crawl_start(SOURCE, "full_text")
        ds.log_crawl_complete(log_id, 7)
        row = _row(client, log_id)
        assert (row.status, row.article_count, row.error_msg) == ("completed", 7, None)

    def test_an_overlong_note_is_truncated_not_dropped(self, client, ds):
        log_id = ds.log_crawl_start(SOURCE, "full_text")
        ds.log_crawl_complete(log_id, 0, note="source-wide fetch failure: " + "x" * 5000)
        row = _row(client, log_id)
        assert row.error_msg.startswith("source-wide fetch failure: ") and len(row.error_msg) == 1000


class TestSourceWideVerdictEndToEnd:
    """The service's own source-wide branch, with only the crawler and the stores
    mocked: 25 sitemaps (above SITEMAP_SOURCE_FAILURE_MIN), every one `HTTP 403`."""

    def test_a_blocked_source_leaves_its_verdict_on_the_real_row(self, client, ds):
        from newscrawler.core.constants import SITEMAP_SOURCE_FAILURE_MIN
        from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
        from newscrawler.infrastructure.datasource.scrapers.crawler import NewsDetailsBatch

        n = max(SITEMAP_SOURCE_FAILURE_MIN, 25)
        repo = MagicMock()
        repo.log_crawl_start = ds.log_crawl_start
        repo.log_crawl_complete = ds.log_crawl_complete
        repo.log_crawl_failed = ds.log_crawl_failed
        repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=i, category="news") for i in range(1, n + 1)]
        with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
            service = CrawlerServiceImpl(data_flow_repo=repo)
        crawler = MagicMock()
        crawler.batch_crawling_details.side_effect = lambda news, website_name, throttle=None: NewsDetailsBatch(
            [], failures={s.sitemap_id: "HTTP 403" for s in news})
        service.crawler_dict = {SOURCE: crawler}

        service.crawl_newsdetails(SOURCE)

        with client.get_session() as s:
            row = s.execute(text("SELECT status, article_count, error_msg FROM crawl_log "
                                 "WHERE website = :w AND task = 'full_text' ORDER BY log_id DESC LIMIT 1"),
                            {"w": SOURCE}).fetchone()
        assert row.status == "completed" and row.article_count == 0
        assert row.error_msg.startswith("source-wide fetch failure: %d/%d (100%%)" % (n, n))
        assert "'HTTP 403': %d" % n in row.error_msg
