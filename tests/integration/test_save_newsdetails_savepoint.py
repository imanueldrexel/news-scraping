"""
SYS-15 against a live PostgreSQL: a per-row DB error (e.g. an FK violation from a
bad sitemap_id) must not poison the whole save_newsdetails transaction. Before the
fix, one bad row aborted the session's transaction; every subsequent row's
session.execute() then raised psycopg2.errors.InFailedSqlTransaction, and the final
session.commit() ran as a silent no-op rollback -- save_newsdetails returned
normally while persisting zero rows from the entire batch, including otherwise-good
ones.

Requires the newsaggregator_test DB (tests/integration/conftest.py forces it) with
scripts/migrate_articles_unique_sitemap.sql applied (articles_sitemap_id_uq).
"""
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


@pytest.fixture
def good_sitemap_id(client):
    with client.get_session() as s:
        row = s.execute(
            text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                "VALUES ('t', 'https://x/SYS-15-savepoint-test', 'TEST', 20260916) "
                "RETURNING sitemap_id"
            )
        ).fetchone()
        s.commit()
    sm_id = row.sitemap_id
    yield sm_id
    with client.get_session() as s:
        s.execute(text("DELETE FROM articles WHERE sitemap_id = :id"), {"id": sm_id})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = :id"), {"id": sm_id})
        s.commit()


class TestSaveNewsdetailsSavepointIsolation:
    def test_bad_row_does_not_drop_good_rows_in_same_batch(self, client, good_sitemap_id):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )
        from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
            NewsDetailsModel,
        )

        ds = SQLAlchemyArticleDataSource(client)
        bad_row = NewsDetailsModel(
            sitemap_id=-999999, extracted_text=["para"], reporter=[], meta_data={}, is_embedded=False
        )
        good_row = NewsDetailsModel(
            sitemap_id=good_sitemap_id, extracted_text=["para"], reporter=[], meta_data={}, is_embedded=False
        )

        # Bad row first, matching the FK-violation-then-InFailedSqlTransaction
        # ordering from the SYS-15 evidence.
        ds.save_newsdetails([bad_row, good_row])

        with client.get_session() as s:
            count = s.execute(
                text("SELECT COUNT(*) FROM articles WHERE sitemap_id = :id"),
                {"id": good_sitemap_id},
            ).scalar()
        assert count == 1
