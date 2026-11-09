"""
SYS-23: save_digest's INSERT used ":categories::jsonb" / ":source_ids::jsonb" --
SQLAlchemy's text() does not recognize a ":name" bind param when immediately
followed by "::" (the Postgres cast operator), so it left those two tokens as
literal, unsubstituted SQL text. Every call to save_digest raised a syntax error;
task=newsletter has never completed. CAST(:name AS jsonb) has no such ambiguity.
"""
from datetime import date
from unittest.mock import MagicMock

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
    SQLAlchemyNewsletterDataSource,
)


def _ds_with_mock_session():
    client = MagicMock()
    session = MagicMock()
    session.execute.return_value.fetchone.return_value.digest_id = 1
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    return SQLAlchemyNewsletterDataSource(client), session


class TestSaveDigestSql:
    def test_categories_and_source_ids_are_real_bind_parameters(self):
        ds, session = _ds_with_mock_session()

        ds.save_digest(
            digest_date=date(2026, 6, 2), file_path="digests/2026-06-02.md",
            cluster_count=56, article_count=589,
            categories={"finance": 10}, source_ids=[1, 2, 3], generation_ms=1000,
        )

        stmt = session.execute.call_args[0][0]
        compiled = stmt.compile()
        # If SQLAlchemy failed to recognize the param (the SYS-23 bug), it would
        # not appear in compiled.params at all -- it would be embedded as literal,
        # unsubstituted text in the compiled SQL string instead.
        assert "categories" in compiled.params
        assert "source_ids" in compiled.params
        assert ":categories::jsonb" not in str(compiled)
        assert ":source_ids::jsonb" not in str(compiled)

    def test_bound_values_are_the_json_strings_passed_in(self):
        ds, session = _ds_with_mock_session()

        ds.save_digest(
            digest_date=date(2026, 6, 2), file_path="digests/2026-06-02.md",
            cluster_count=1, article_count=1,
            categories={"a": 1}, source_ids=["KOMPAS"], generation_ms=1,
        )

        params = session.execute.call_args[0][1]
        assert params["categories"] == '{"a": 1}'
        assert params["source_ids"] == '["KOMPAS"]'

    def test_commits_and_returns_digest_id(self):
        ds, session = _ds_with_mock_session()

        result = ds.save_digest(
            digest_date=date(2026, 6, 2), file_path="digests/2026-06-02.md",
            cluster_count=1, article_count=1,
            categories={}, source_ids=[], generation_ms=1,
        )

        assert result == 1
        session.commit.assert_called_once()
