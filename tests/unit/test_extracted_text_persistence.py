"""
SYS-18: articles.extracted_text is a `text` column but NewsDetailsModel.extracted_text
is a List[str] of paragraphs. Binding the list straight to the column let psycopg2
adapt it as a Postgres array literal (`{"para1","para2"}`) instead of storing prose --
every downstream reader (knowledge extractor prompts, entity_mentions context
snippets, backfill tooling) got the mangled form. The fix joins paragraphs with a
blank line before the value reaches the driver, matching the format the trafilatura
fallback already uses (crawler.py splits its output on "\n\n").
No database needed: asserts on the compiled statement's bound parameters.
"""
from sqlalchemy.dialects import postgresql

from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
    SQLAlchemyArticleDataSource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import (
    NewsArticlesTable,
)
from unittest.mock import MagicMock


def make_details_model(**kwargs):
    defaults = dict(
        sitemap_id=1,
        extracted_text=["paragraph one", "paragraph two"],
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


def _bound_extracted_text(session):
    stmt = session.execute.call_args_list[0][0][0]   # the INSERT; the last call is DBT-11's chunks.article_id link
    compiled = stmt.compile(dialect=postgresql.dialect())
    return compiled.params["extracted_text"]


class TestSaveNewsdetailsJoinsParagraphsIntoProse:
    def test_paragraphs_are_joined_with_blank_line_not_a_python_list(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(extracted_text=["para one", "para two"])])

        assert _bound_extracted_text(session) == "para one\n\npara two"

    def test_single_paragraph_round_trips_unchanged(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(extracted_text=["only paragraph"])])

        assert _bound_extracted_text(session) == "only paragraph"

    def test_empty_paragraph_list_becomes_empty_string_not_empty_array_literal(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(extracted_text=[])])

        assert _bound_extracted_text(session) == ""

    def test_blank_paragraphs_are_dropped(self):
        data_source, session = _data_source_with_mock_session()

        data_source.save_newsdetails([make_details_model(extracted_text=["real", "", "  ", "text"])])

        assert _bound_extracted_text(session) == "real\n\ntext"


class TestNewsArticlesTableConstructorMatchesTheWritePath:
    def test_orm_constructor_also_joins_paragraphs(self):
        entry = NewsArticlesTable(make_details_model(extracted_text=["a", "b"]))
        assert entry.extracted_text == "a\n\nb"
        assert isinstance(entry.extracted_text, str)
