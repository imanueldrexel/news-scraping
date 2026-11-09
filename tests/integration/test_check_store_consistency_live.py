"""
DBT-45 (#187): check_store_consistency.gather_counts() against a live
PostgreSQL. SRC-53's `sitemaps_url_category` check was only ever tested through
the pure compute_divergence(); its SQL could have been `WHERE false` and its
value dropped before compute_divergence without any test failing. Here a real
sitemaps row with a URL category must be counted and reported as GROWING.
FAISS paths point at an empty tmp dir, so no index is read.
"""
import importlib.util
import os
import sys

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

SOURCE = "DBT45TEST"
_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "scripts", "check_store_consistency.py")


@pytest.fixture
def csc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_store_consistency", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", ["check_store_consistency.py"])
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L1", str(tmp_path / "NEWS_L1"))
    monkeypatch.setattr(mod, "VECTOR_DB_NAME_L2", str(tmp_path / "NEWS_L2"))
    return mod


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
        s.execute(text("DELETE FROM chunks WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources = :s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


def _insert(client, link, category):
    with client.get_session() as s:
        s.execute(text("INSERT INTO sitemaps (headline, link, sources, category, posted_at) "
                       "VALUES ('t', :l, :s, :c, 20260926)"), {"l": link, "s": SOURCE, "c": category})
        s.commit()


class TestSitemapsUrlCategory:
    def test_a_url_category_is_counted_and_growing(self, client, csc):
        before = csc.gather_counts()["sitemaps_url_category"]
        _insert(client, "http://dbt45.test/a", "https://www.example.co.id/sitemap/news-2026.xml")
        _insert(client, "http://dbt45.test/b", "ekonomi")
        counts = csc.gather_counts()
        assert counts["sitemaps_url_category"] == before + 1
        assert "sitemaps_url_category" in csc.growing_checks(counts)


def _insert_l2_chunk(client, link, words):
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, category, posted_at) "
                             "VALUES ('t', :l, :s, 'ekonomi', 20261012) RETURNING sitemap_id"),
                        {"l": link, "s": SOURCE}).scalar()
        s.execute(text("INSERT INTO chunks (sitemap_id, chunk_level, chunk_index, chunk_total, is_first_chunk, "
                       "is_last_chunk, text_content, token_count, embedding_id, chunk_status) "
                       "VALUES (:sid, 2, 0, 1, true, true, :t, :n, NULL, 'pending_embedding')"),
                  {"sid": sid, "t": " ".join(["kata"] * words), "n": words})
        s.commit()


class TestOversizedL2Rows:
    """SYS-137 (#316): the count comes from the database, against CHUNK_MAX_TOKENS."""

    def test_a_200_word_l2_row_is_counted_and_growing_an_80_word_one_is_not(self, client, csc):
        before = csc.gather_counts()["l2_over_max_tokens"]
        _insert_l2_chunk(client, "http://sys137.test/a", 200)
        _insert_l2_chunk(client, "http://sys137.test/b", csc.CHUNK_MAX_TOKENS)
        counts = csc.gather_counts()
        assert counts["l2_over_max_tokens"] == before + 1
        assert "l2_over_max_tokens" in csc.growing_checks(counts)
