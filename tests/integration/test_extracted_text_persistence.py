"""
SYS-18 against a live PostgreSQL: articles.extracted_text must be stored as prose,
not the Postgres array-literal form psycopg2 produces when a Python list is bound
directly to a `text` column. Confirms the fix round-trips through the real driver,
not just through a mocked-statement compile.
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
                "VALUES ('t', 'https://x/SYS-18-persistence-test', 'TEST', 20260916) "
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


class TestExtractedTextStoredAsProse:
    def test_paragraph_list_round_trips_to_prose_not_an_array_literal(self, client, sitemap_id):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
            SQLAlchemyArticleDataSource,
        )
        from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
            NewsDetailsModel,
        )

        ds = SQLAlchemyArticleDataSource(client)
        ds.save_newsdetails([
            NewsDetailsModel(
                sitemap_id=sitemap_id,
                extracted_text=["Paragraf pertama, dengan koma.", 'Paragraf kedua "dikutip".'],
                reporter=[],
                meta_data={},
                is_embedded=False,
            )
        ])

        with client.get_session() as s:
            stored = s.execute(
                text("SELECT extracted_text FROM articles WHERE sitemap_id = :id"),
                {"id": sitemap_id},
            ).scalar()

        assert stored == 'Paragraf pertama, dengan koma.\n\nParagraf kedua "dikutip".'
        assert not stored.startswith('{"')
