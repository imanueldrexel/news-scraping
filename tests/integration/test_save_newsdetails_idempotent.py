"""
DBT-07 against a live PostgreSQL: save_newsdetails must be idempotent per
sitemap_id. Before the fix, a plain INSERT let a re-crawl create a second
`articles` row for the same sitemap_id -- production held 617 such duplicates.

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
def sitemap_id(client):
    with client.get_session() as s:
        row = s.execute(
            text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                "VALUES ('t', 'https://x/DBT-07-idempotent-test', 'TEST', 20260916) "
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


class TestSaveNewsdetailsIdempotentLive:
    def test_saving_the_same_sitemap_twice_leaves_one_row(self, client, sitemap_id):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )
        from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
            NewsDetailsModel,
        )

        ds = SQLAlchemyArticleDataSource(client)
        model = NewsDetailsModel(
            sitemap_id=sitemap_id, extracted_text=["para"], reporter=[], meta_data={}, is_embedded=False
        )

        ds.save_newsdetails([model])
        ds.save_newsdetails([model])  # simulates a re-crawl of the same sitemap

        with client.get_session() as s:
            count = s.execute(
                text("SELECT COUNT(*) FROM articles WHERE sitemap_id = :id"), {"id": sitemap_id}
            ).scalar()
        assert count == 1
