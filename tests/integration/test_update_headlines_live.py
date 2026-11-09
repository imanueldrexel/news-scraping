"""
SYS-33 (#114): SQLAlchemySitemapDataSource.update_headlines against a real
table -- the write-back that turns a URL-slug placeholder into the page's
og:title. Asserted on what comes back from the DB, not on the SQL text.
"""
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "SYS33TEST"


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _seed(client, headline):
    with client.get_session() as s:
        sid = s.execute(
            text("INSERT INTO sitemaps (headline, link, sources, posted_at, crawl_status) "
                 "VALUES (:h, :l, :s, 20260920, 'pending') RETURNING sitemap_id"),
            {"h": headline, "l": f"https://sys33.test/{uuid.uuid4().hex}", "s": SOURCE},
        ).scalar()
        s.commit()
    return sid


def _headline(client, sid):
    with client.get_session() as s:
        return s.execute(text("SELECT headline FROM sitemaps WHERE sitemap_id = :id"), {"id": sid}).scalar()


class TestUpdateHeadlinesLive:
    def test_placeholder_is_replaced_and_unchanged_rows_are_not_counted(self, client):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        ds = SQLAlchemySitemapDataSource(client)
        placeholder = _seed(client, "Rupiah Dan Ihsg Menguat Hca5")
        already_real = _seed(client, "Rupiah dan IHSG Menguat")
        untouched = _seed(client, "Other Row")

        changed = ds.update_headlines({
            placeholder: "Rupiah dan IHSG Menguat, Ini Pergerakannya",
            already_real: "Rupiah dan IHSG Menguat",   # same value -> no-op
            untouched: "   ",                           # blank -> skipped
        })

        assert changed == 1
        assert _headline(client, placeholder) == "Rupiah dan IHSG Menguat, Ini Pergerakannya"
        assert _headline(client, already_real) == "Rupiah dan IHSG Menguat"
        assert _headline(client, untouched) == "Other Row"

    def test_empty_mapping_is_a_no_op(self, client):
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            SQLAlchemySitemapDataSource,
        )
        assert SQLAlchemySitemapDataSource(client).update_headlines({}) == 0
