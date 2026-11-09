"""
SYS-19: SQLAlchemyKnowledgeDataSource's poison-pill support -- the pending-extraction
query excludes articles that have exhausted their attempt budget and orders failing
articles behind fresh ones, record_extraction_failure increments that budget, and the
session-aware write methods let KnowledgeExtractor batch an article's writes into one
transaction.
"""
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
    SQLAlchemyKnowledgeDataSource,
)


def _ds_with_session():
    client = MagicMock()
    session = MagicMock()
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    return SQLAlchemyKnowledgeDataSource(client), session


class TestGetArticlesPendingExtractionExcludesExhaustedAttempts:
    def test_max_attempts_is_bound_into_the_query(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchall.return_value = []
        ds.get_articles_pending_extraction(batch_size=50, max_attempts=3)
        params = session.execute.call_args[0][1]
        assert params["batch_size"] == 50 and params["max_attempts"] == 3
        from newscrawler.core.filter_rubric import TOPICS_FINANCE
        assert params["finance_topics"] == list(TOPICS_FINANCE)

    def test_default_max_attempts_comes_from_the_constant(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchall.return_value = []
        ds.get_articles_pending_extraction(batch_size=50)
        from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
        params = session.execute.call_args[0][1]
        assert params["max_attempts"] == KNOWLEDGE_EXTRACT_MAX_ATTEMPTS

    def test_query_orders_by_attempts_before_posted_at(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchall.return_value = []
        ds.get_articles_pending_extraction(batch_size=50)
        sql_text = str(session.execute.call_args[0][0])
        assert "knowledge_extract_attempts < :max_attempts" in sql_text
        order_clause = sql_text.split("ORDER BY", 1)[1]
        assert order_clause.strip().startswith("a.knowledge_extract_attempts")


class TestRecordExtractionFailure:
    def test_increments_attempts_and_sets_error_on_its_own_commit(self):
        ds, session = _ds_with_session()
        ds.record_extraction_failure(9, "boom")
        session.execute.assert_called_once()
        params = session.execute.call_args[0][1]
        assert params["article_id"] == 9
        assert params["error_msg"] == "boom"
        session.commit.assert_called_once()

    def test_error_message_is_truncated(self):
        ds, session = _ds_with_session()
        ds.record_extraction_failure(9, "x" * 5000)
        params = session.execute.call_args[0][1]
        assert len(params["error_msg"]) == 1000

    def test_none_error_message_does_not_raise(self):
        ds, session = _ds_with_session()
        ds.record_extraction_failure(9, None)
        params = session.execute.call_args[0][1]
        assert params["error_msg"] == ""


class TestSessionAwareWrites:
    def test_upsert_entity_uses_the_given_session_without_committing(self):
        ds, standalone_session = _ds_with_session()
        shared_session = MagicMock()
        shared_session.execute.return_value.fetchone.return_value.entity_id = 42
        from newscrawler.infrastructure.datasource.dataflow.model.entity_model import EntityModel
        model = EntityModel(name="BCA", normalized_name="bca", entity_type="ORGANIZATION",
                            subtype=None, ticker="BBCA", first_seen_at=None, last_seen_at=None)

        result = ds.upsert_entity(model, session=shared_session)

        assert result == 42
        shared_session.commit.assert_not_called()
        standalone_session.execute.assert_not_called()

    def test_upsert_entity_without_a_session_opens_and_commits_its_own(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchone.return_value.entity_id = 7
        from newscrawler.infrastructure.datasource.dataflow.model.entity_model import EntityModel
        model = EntityModel(name="BCA", normalized_name="bca", entity_type="ORGANIZATION",
                            subtype=None, ticker="BBCA", first_seen_at=None, last_seen_at=None)

        result = ds.upsert_entity(model)

        assert result == 7
        session.commit.assert_called_once()

    def test_mark_article_extracted_uses_the_given_session_without_committing(self):
        ds, standalone_session = _ds_with_session()
        shared_session = MagicMock()

        ds.mark_article_extracted(9, session=shared_session)

        shared_session.execute.assert_called_once()
        shared_session.commit.assert_not_called()
        standalone_session.execute.assert_not_called()

    def test_insert_entity_mention_uses_the_given_session_without_committing(self):
        ds, standalone_session = _ds_with_session()
        shared_session = MagicMock()
        from newscrawler.infrastructure.datasource.dataflow.model.entity_model import EntityMentionModel
        model = EntityMentionModel(entity_id=1, sitemap_id=2, article_id=3, chunk_id=None,
                                   context_snippet="x", event_type=None, posted_at=None, source="S")

        ds.insert_entity_mention(model, session=shared_session)

        shared_session.execute.assert_called_once()
        shared_session.commit.assert_not_called()
        standalone_session.execute.assert_not_called()


class TestFinanceTopicsFirst:
    """SYS-39 (#125): within an attempt count the finance topics are extracted
    first; a catch-up never leaves ticker lookups waiting behind general news."""

    def _sql(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchall.return_value = []
        ds.get_articles_pending_extraction(batch_size=50)
        return " ".join(str(session.execute.call_args[0][0]).split())

    def test_finance_comes_after_the_attempt_count_and_before_recency(self):
        order = self._sql().split("ORDER BY", 1)[1]
        attempts = order.index("a.knowledge_extract_attempts ASC")
        finance = order.index("COALESCE(a.topic = ANY(:finance_topics), FALSE) DESC")
        recency = order.index("s.posted_at DESC")
        assert attempts < finance < recency

    def test_an_article_with_no_topic_is_not_finance(self):
        assert "COALESCE(a.topic = ANY(:finance_topics), FALSE)" in self._sql()


class TestApiUsage:
    def test_today_usage_reads_calls_tokens_and_dollars(self):
        ds, session = _ds_with_session()
        row = MagicMock(call_count=12, input_tokens=9000, output_tokens=3600, cost_usd="0.003510")
        session.execute.return_value.fetchone.return_value = row
        usage = ds.get_today_api_usage("deepseek-v4-flash")
        assert usage == (12, 9000, 3600, 0.00351) and isinstance(usage.cost_usd, float)
        assert session.execute.call_args[0][1] == {"api_name": "deepseek-v4-flash"}

    def test_a_model_not_used_today_is_all_zeros(self):
        ds, session = _ds_with_session()
        session.execute.return_value.fetchone.return_value = None
        assert tuple(ds.get_today_api_usage("m")) == (0, 0, 0, 0.0)

    def test_increment_adds_tokens_and_cost_to_the_days_row(self):
        ds, session = _ds_with_session()
        ds.increment_api_call_count("m", input_tokens=700, output_tokens=300, cost_usd=0.000285)
        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert session.execute.call_args[0][1] == {"api_name": "m", "input_tokens": 700,
                                                   "output_tokens": 300, "cost_usd": 0.000285}
        assert "call_count = api_usage_log.call_count + 1" in sql
        assert "input_tokens = api_usage_log.input_tokens + EXCLUDED.input_tokens" in sql
        assert "output_tokens = api_usage_log.output_tokens + EXCLUDED.output_tokens" in sql
        assert "cost_usd = api_usage_log.cost_usd + EXCLUDED.cost_usd" in sql
        session.commit.assert_called_once()

    def test_a_call_count_only_increment_adds_zero_tokens(self):
        """The summarizer counts calls only."""
        ds, session = _ds_with_session()
        ds.increment_api_call_count("m")
        assert session.execute.call_args[0][1] == {"api_name": "m", "input_tokens": 0,
                                                   "output_tokens": 0, "cost_usd": 0.0}


class TestMigration:
    def test_it_is_registered_and_idempotent(self):
        import os
        import re
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sql = open(os.path.join(root, "scripts", "migrate_api_usage_tokens.sql"), encoding="utf-8").read()
        statements = [s for s in re.findall(r"^ALTER TABLE .*?;", sql, flags=re.M | re.S)]
        assert len(statements) == 3 and all("ADD COLUMN IF NOT EXISTS" in s for s in statements)
        for column in ("input_tokens", "output_tokens", "cost_usd"):
            assert column in sql
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.knowledge_table import ApiUsageLogTable
        assert {"input_tokens", "output_tokens", "cost_usd"} <= set(ApiUsageLogTable.__table__.columns.keys())
        spec_path = os.path.join(root, "scripts", "migrate.py")
        assert '"migrate_api_usage_tokens.sql"' in open(spec_path, encoding="utf-8").read()
