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
