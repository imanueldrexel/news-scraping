"""SYS-39 (#125) against the real schema (newsaggregator_test): api_usage_log keeps
the day's calls, tokens and dollars per model, and the pending-extraction query puts
finance topics first within an attempt count. Needs migrate_api_usage_tokens.sql
applied to the test DB (scripts/migrate.py)."""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS39"
MODEL = "sys39-test-model"


@pytest.fixture
def ds():
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield SQLAlchemyKnowledgeDataSource(client)
    with client.get_session() as s:
        s.execute(text("DELETE FROM api_usage_log WHERE api_name LIKE 'sys39%'"))
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources=:s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _article(ds, topic, posted_at, attempts=0):
    with ds.client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                             "VALUES ('t', :l, :s, :p) RETURNING sitemap_id"),
                        {"l": f"https://sys39.test/{uuid.uuid4().hex}", "s": SOURCE, "p": posted_at}).scalar()
        aid = s.execute(text("INSERT INTO articles (sitemap_id, extracted_text, topic, knowledge_extract_attempts) "
                             "VALUES (:id, 'x', :t, :a) RETURNING articles_id"),
                        {"id": sid, "t": topic, "a": attempts}).scalar()
        s.commit()
    return aid


def _pending(ds):
    return [a["article_id"] for a in ds.get_articles_pending_extraction(500) if a["source"] == SOURCE]


class TestUsage:
    def test_nothing_today_is_zeros(self, ds):
        assert tuple(ds.get_today_api_usage(MODEL)) == (0, 0, 0, 0.0)

    def test_calls_tokens_and_dollars_add_up_per_model(self, ds):
        ds.increment_api_call_count(MODEL, input_tokens=700, output_tokens=300, cost_usd=0.000285)
        ds.increment_api_call_count(MODEL, input_tokens=800, output_tokens=250, cost_usd=0.00027)
        ds.increment_api_call_count("sys39-other", input_tokens=5, output_tokens=5, cost_usd=1.0)
        usage = ds.get_today_api_usage(MODEL)
        assert (usage.call_count, usage.input_tokens, usage.output_tokens) == (2, 1500, 550)
        assert usage.cost_usd == pytest.approx(0.000555)
        assert ds.get_today_api_usage("sys39-other").cost_usd == pytest.approx(1.0)

    def test_a_calls_only_increment_still_counts_the_call(self, ds):
        """The summarizer's form; the old call count keeps working beside it."""
        ds.increment_api_call_count(MODEL)
        ds.increment_api_call_count(MODEL)
        assert ds.get_today_api_call_count(MODEL) == 2
        assert tuple(ds.get_today_api_usage(MODEL))[1:] == (0, 0, 0.0)


class TestFinanceFirst:
    def test_finance_topics_come_before_newer_general_news(self, ds):
        general_new = _article(ds, "politics_government", 20260930)
        finance_old = _article(ds, "markets", 20260901)
        finance_older = _article(ds, "macro_policy", 20260801)
        no_topic = _article(ds, None, 20260929)
        assert _pending(ds) == [finance_old, finance_older, general_new, no_topic]

    def test_a_once_failed_finance_article_still_sinks_behind_fresh_ones(self, ds):
        """SYS-19's rule is kept: attempts first, then finance."""
        failed_finance = _article(ds, "markets", 20260930, attempts=1)
        fresh_general = _article(ds, "politics_government", 20260801)
        assert _pending(ds) == [fresh_general, failed_finance]

    def test_an_exhausted_article_is_not_offered(self, ds):
        from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
        exhausted = _article(ds, "markets", 20260930, attempts=KNOWLEDGE_EXTRACT_MAX_ATTEMPTS)
        assert exhausted not in _pending(ds)
