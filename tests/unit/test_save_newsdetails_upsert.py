"""
DBT-07: save_newsdetails must upsert on sitemap_id instead of a plain insert, so a
re-crawl of an already-saved sitemap does not create a duplicate `articles` row.
No database needed: asserts on the compiled SQL of the statement passed to
session.execute(), with the session itself mocked.
"""
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
    SQLAlchemyArticleDataSource,
)


def make_details_model(**kwargs):
    defaults = dict(
        sitemap_id=1,
        extracted_text=["paragraph"],
        reporter=[],
        meta_data={},
        is_embedded=True,
    )
    defaults.update(kwargs)
    return NewsDetailsModel(**defaults)


def _data_source_with_mock_session():
    data_source = SQLAlchemyArticleDataSource.__new__(SQLAlchemyArticleDataSource)
    session = MagicMock(name="session")
    client = MagicMock(name="client")
    client.get_session.return_value.__enter__.return_value = session
    client.get_session.return_value.__exit__.return_value = False
    data_source.client = client
    return data_source, session


class TestSaveNewsdetailsUpsert:
    def test_statement_is_on_conflict_do_nothing_on_sitemap_id(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(sitemap_id=99)])

        assert session.execute.call_count == 1
        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "INSERT INTO articles" in compiled
        assert "ON CONFLICT (sitemap_id) DO NOTHING" in compiled

    def test_commits_once_after_all_rows(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(sitemap_id=1), make_details_model(sitemap_id=2)])

        assert session.execute.call_count == 2
        session.commit.assert_called_once()

    def test_one_row_failing_does_not_abort_the_rest(self):
        data_source, session = _data_source_with_mock_session()
        session.execute.side_effect = [Exception("boom"), None]

        data_source.save_newsdetails([make_details_model(sitemap_id=1), make_details_model(sitemap_id=2)])

        assert session.execute.call_count == 2
        session.commit.assert_called_once()
