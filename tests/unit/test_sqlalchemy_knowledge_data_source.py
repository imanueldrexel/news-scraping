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
        assert params == {"batch_size": 50, "max_attempts": 3}

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
