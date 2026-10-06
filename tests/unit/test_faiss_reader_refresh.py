"""DBT-16 (#51): the web UI loads NEWS_L1/L2 once, and the crawler (another
process) saves them after every source. A reader must pick up a newer
generation without a restart, and /api/health must show what it searches."""
from unittest.mock import MagicMock, patch

import pytest
from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import FAISS

from newscrawler.infrastructure.datasource.dataflow.write.faiss import chunk_faiss_data_source as cfd
from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource


def _save_new_generation(texts, db_name):
    vs = FAISS.from_texts(texts, FakeEmbeddings(size=8))
    index_generation.track_disk(vs, db_name)
    ChunkFAISSDatasource._atomic_save_local(vs, db_name)


@pytest.fixture
def reader(tmp_path, monkeypatch):
    l1, l2 = str(tmp_path / "NEWS_L1"), str(tmp_path / "NEWS_L2")
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L1", l1)
    monkeypatch.setattr(cfd, "VECTOR_DB_NAME_L2", l2)
    _save_new_generation(["l1 a"], l1)
    _save_new_generation(["l2 a", "l2 b"], l2)
    ds = ChunkFAISSDatasource.__new__(ChunkFAISSDatasource)
    ds.embedding_model = FakeEmbeddings(size=8)
    ds.vs_l1 = ds._load_or_create(l1)
    ds.vs_l2 = ds._load_or_create(l2)
    return ds, l1, l2


class TestRefreshStale:
    def test_nothing_changed_nothing_reloaded(self, reader):
        ds, _, _ = reader
        before = ds.vs_l2
        assert ds.refresh_stale() == []
        assert ds.vs_l2 is before

    def test_a_level_another_process_saved_is_reloaded(self, reader):
        ds, l1, l2 = reader
        old_l1, old_loaded = ds.vs_l1, dict(ds.loaded_at)
        _save_new_generation(["l2 a", "l2 b", "article crawled after the web loaded"], l2)

        assert ds.refresh_stale() == [l2]
        assert ds.vs_l2.index.ntotal == 3
        assert "article crawled after the web loaded" in {d.page_content for d in ds.vs_l2.docstore._dict.values()}
        assert ds.vs_l1 is old_l1, "an unchanged level is not reloaded"
        assert ds.loaded_at[l2] > old_loaded[l2]
        assert ds.refresh_stale() == [], "the reloaded generation is now the current one"

    def test_a_search_in_flight_keeps_its_index(self, reader):
        ds, _, l2 = reader
        held = ds.vs_l2
        _save_new_generation(["x", "y", "z", "w"], l2)
        ds.refresh_stale()
        assert held.index.ntotal == 2 and ds.vs_l2.index.ntotal == 4


class TestWebRefresh:
    @pytest.fixture
    def web(self, monkeypatch):
        from newscrawler.web import app as web_app
        ds = MagicMock()
        monkeypatch.setattr(web_app, "_faiss_ds", ds)
        monkeypatch.setattr(web_app, "_last_reload_check", 0.0)
        return web_app, ds

    def test_checks_at_most_once_per_interval(self, web, monkeypatch):
        web_app, ds = web
        monkeypatch.setattr(web_app, "FAISS_RELOAD_CHECK_S", 3600)
        web_app._refresh_faiss_if_stale()
        web_app._refresh_faiss_if_stale()
        assert ds.refresh_stale.call_count == 1

    def test_checks_on_every_query_with_a_zero_interval(self, web, monkeypatch):
        web_app, ds = web
        monkeypatch.setattr(web_app, "FAISS_RELOAD_CHECK_S", 0)
        web_app._refresh_faiss_if_stale()
        web_app._refresh_faiss_if_stale()
        assert ds.refresh_stale.call_count == 2

    def test_a_failed_reload_does_not_fail_the_query(self, web, monkeypatch, caplog):
        web_app, ds = web
        monkeypatch.setattr(web_app, "FAISS_RELOAD_CHECK_S", 0)
        ds.refresh_stale.side_effect = OSError("index.faiss locked by a scanner")
        with caplog.at_level("ERROR"):
            web_app._refresh_faiss_if_stale()
        assert any("FAISS reload failed" in r.getMessage() for r in caplog.records)

    def test_run_query_refreshes_before_searching(self, web, monkeypatch):
        web_app, ds = web
        order = []
        processor = MagicMock()
        processor.query.side_effect = lambda **k: order.append("query") or {}
        ds.refresh_stale.side_effect = lambda: order.append("refresh")
        monkeypatch.setattr(web_app, "_get_processor", lambda: processor)
        monkeypatch.setattr(web_app, "FAISS_RELOAD_CHECK_S", 0)
        web_app._run_query(question="q")
        assert order == ["refresh", "query"]

    def test_the_page_retrieval_refreshes_before_searching(self, web, monkeypatch):
        # ADR-005: the page searches through _retrieve (step one of a turn), not _run_query.
        web_app, ds = web
        order = []
        processor = MagicMock()
        processor.retrieve.side_effect = lambda *a, **k: order.append("retrieve") or []
        ds.refresh_stale.side_effect = lambda: order.append("refresh")
        monkeypatch.setattr(web_app, "_get_processor", lambda: processor)
        monkeypatch.setattr(web_app, "FAISS_RELOAD_CHECK_S", 0)
        web_app._retrieve("q", None)
        assert order == ["refresh", "retrieve"]

    def test_health_shows_what_this_process_searches(self, web):
        web_app, ds = web
        ds.vs_l1.index.ntotal, ds.vs_l2.index.ntotal = 5, 9
        ds.loaded_at = {web_app_constants().VECTOR_DB_NAME_L2: "2026-09-29T06:00:00+00:00"}
        mem = web_app._faiss_in_memory()
        assert mem["NEWS_L1"]["docs"] == 5 and mem["NEWS_L2"]["docs"] == 9
        assert mem["NEWS_L2"]["loaded_at"] == "2026-09-29T06:00:00+00:00"

    def test_health_before_the_first_query(self, monkeypatch):
        from newscrawler.web import app as web_app
        monkeypatch.setattr(web_app, "_faiss_ds", None)
        assert web_app._faiss_in_memory() is None


def web_app_constants():
    from newscrawler.core import constants
    return constants
