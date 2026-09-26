"""
SYS-54 (#185) against a live PostgreSQL: which sitemaps the crawl may strip of
their vectors and chunk rows. Terminal = no articles row AND (rejected_filter OR
fetch_failures at the cap), the rule repair_store_consistency uses (OPS-25).
"""
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES  # noqa: E402

SOURCE = "SYS54TEST"


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            assert s.execute(text("SELECT current_database()")).scalar() == "newsaggregator_test"
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        ids = "SELECT sitemap_id FROM sitemaps WHERE sources = :s"
        s.execute(text(f"DELETE FROM chunks WHERE sitemap_id IN ({ids})"), {"s": SOURCE})
        s.execute(text(f"DELETE FROM articles WHERE sitemap_id IN ({ids})"), {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _sitemap(client, name, status="pending", failures=0, article=False, chunks=0):
    with client.get_session() as s:
        sid = s.execute(text(
            "INSERT INTO sitemaps (headline, link, sources, posted_at, crawl_status, fetch_failures) "
            "VALUES ('t', :l, :s, 20260926, :st, :f) RETURNING sitemap_id"),
            {"l": "http://sys54.test/" + name, "s": SOURCE, "st": status, "f": failures}).scalar()
        if article:
            s.execute(text("INSERT INTO articles (sitemap_id, extracted_text) VALUES (:i, 'x')"), {"i": sid})
        for idx in range(chunks):
            s.execute(text(
                "INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                "VALUES (:i, 2, :x, :n, :x = 0, :x = :n - 1, 'c', 1, :e, 'embedded')"),
                {"i": sid, "x": idx, "n": chunks, "e": "v-%d-%d" % (sid, idx)})
        s.commit()
    return sid


def test_terminal_is_no_article_and_rejected_or_at_the_fetch_cap(client):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
        SQLAlchemySitemapDataSource)
    ds = SQLAlchemySitemapDataSource(client)
    rejected = _sitemap(client, "rejected", status="rejected_filter")
    dead = _sitemap(client, "dead", failures=SITEMAP_MAX_FETCH_FAILURES)
    failing = _sitemap(client, "failing", failures=SITEMAP_MAX_FETCH_FAILURES - 1)
    queued = _sitemap(client, "queued")
    rejected_with_article = _sitemap(client, "old-soft", status="rejected_filter", article=True)
    empty = _sitemap(client, "empty", status="empty_extraction")
    got = ds.terminal_without_article([rejected, dead, failing, queued, rejected_with_article, empty])
    assert got == {rejected, dead}


def test_delete_for_sitemaps_removes_only_their_rows(client):
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import (
        SQLAlchemyChunkDataSource)
    doomed = _sitemap(client, "doomed", status="rejected_filter", chunks=3)
    kept = _sitemap(client, "kept", chunks=2)
    assert SQLAlchemyChunkDataSource(client).delete_for_sitemaps([doomed]) == 3
    with client.get_session() as s:
        left = dict(s.execute(text("SELECT sitemap_id, count(*) FROM chunks WHERE sitemap_id = ANY(:i) "
                                   "GROUP BY 1"), {"i": [doomed, kept]}).fetchall())
    assert left == {kept: 2}
