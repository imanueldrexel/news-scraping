"""
Unit tests for scripts/check_store_consistency.py -- the pure divergence arithmetic
(compute_divergence) and the pickle-based docstore reader, both DB-free.
"""
import importlib.util
import os
import pickle
import sys
from types import SimpleNamespace

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "check_store_consistency.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("check_store_consistency", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["check_store_consistency.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


csc = _load()


class TestComputeDivergence:
    def test_everything_consistent_is_all_zero(self):
        counts = csc.compute_divergence(
            l1_ids=[1, 2], l2_ids=[1, 2], articles_ids={1, 2},
            chunks_l1_ids=[1, 2], chunks_l2_ids=[1, 2], pending_embedding_count=0,
        )
        assert all(counts[k] == 0 for k in csc.CHECK_KEYS)
        assert counts["l1_total"] == 2 and counts["l2_total"] == 2

    def test_a_queued_sitemap_without_an_article_is_information_not_a_check(self):
        counts = csc.compute_divergence(
            l1_ids=[1, 2], l2_ids=[1, 2], articles_ids={1},
            chunks_l1_ids=[1, 2], chunks_l2_ids=[1, 2], pending_embedding_count=0,
        )
        assert counts["l1_no_articles_queued"] == 1 and counts["l2_no_articles_queued"] == 1
        assert counts["l1_no_articles_terminal"] == 0 and counts["l2_no_articles_terminal"] == 0
        assert "l1_no_articles_queued" not in csc.CHECK_KEYS
        assert csc.growing_checks(counts) == []

    def test_a_queued_sitemap_turning_terminal_is_growing_the_day_it_happens(self):
        """OPS-25 (#174): SRC-33's retirement flipped 1,237 queued VIVA sitemaps
        with vectors to rejected_filter, and the old combined count did not move
        (6529 6529 KNOWN). The same ids, now terminal, must turn the check red."""
        args = dict(l1_ids=[1, 2, 3], l2_ids=[1, 2, 3], articles_ids={1},
                    chunks_l1_ids=[1, 2, 3], chunks_l2_ids=[1, 2, 3], pending_embedding_count=0)
        before = csc.compute_divergence(**args)
        after = csc.compute_divergence(terminal_ids={3}, **args)
        assert csc.growing_checks(before) == []
        assert after["l1_no_articles_terminal"] == 1 and after["l1_no_articles_queued"] == 1
        assert csc.growing_checks(after) == ["l1_no_articles_terminal", "l2_no_articles_terminal"]

    def test_stored_url_categories_are_a_check(self):
        """SRC-53 (#173): 657 INEWS rows kept a sitemap URL as their category
        after the fleet's live branch keys were all names."""
        counts = csc.compute_divergence([], [], set(), [], [], 0, url_category_rows=657)
        assert counts["sitemaps_url_category"] == 657
        assert csc.growing_checks(counts) == ["sitemaps_url_category"]
        assert csc.compute_divergence([], [], set(), [], [], 0)["sitemaps_url_category"] == 0

    def test_oversized_l2_rows_are_a_check(self):
        """SYS-137 (#316): VIVA articles saved over their June 450-word chunks; the chunker never
        writes one, so any is growth."""
        counts = csc.compute_divergence([], [], set(), [], [], 0, oversized_l2_rows=2012)
        assert counts["l2_over_max_tokens"] == 2012
        assert csc.growing_checks(counts) == ["l2_over_max_tokens"]
        assert csc.compute_divergence([], [], set(), [], [], 0)["l2_over_max_tokens"] == 0

    def test_every_check_has_baseline_zero(self):
        """A baseline above the real count hides that much new damage (OPS-25)."""
        assert all(csc.BASELINE.get(k, 0) == 0 for k in csc.CHECK_KEYS)

    def test_l1_not_in_l2(self):
        counts = csc.compute_divergence(
            l1_ids=[1, 2, 3], l2_ids=[1, 2], articles_ids={1, 2, 3},
            chunks_l1_ids=[1, 2, 3], chunks_l2_ids=[1, 2], pending_embedding_count=0,
        )
        assert counts["l1_not_in_l2"] == 1

    def test_duplicate_l1_vectors_for_the_same_sitemap(self):
        counts = csc.compute_divergence(
            l1_ids=[1, 1, 2], l2_ids=[1, 2], articles_ids={1, 2},
            chunks_l1_ids=[1, 2], chunks_l2_ids=[1, 2], pending_embedding_count=0,
        )
        assert counts["l1_duplicate_sitemaps"] == 1
        assert counts["l1_total"] == 3, "total counts every vector, duplicates included"

    def test_articles_row_with_no_chunks_at_either_level(self):
        counts = csc.compute_divergence(
            l1_ids=[], l2_ids=[], articles_ids={1, 2}, chunks_l1_ids=[1], chunks_l2_ids=[],
            pending_embedding_count=0,
        )
        assert counts["articles_no_chunks"] == 1  # only sitemap 2 has no chunks at all

    def test_chunks_sitemap_id_missing_from_both_faiss_indexes(self):
        counts = csc.compute_divergence(
            l1_ids=[1], l2_ids=[1], articles_ids={1, 2}, chunks_l1_ids=[1], chunks_l2_ids=[1, 2],
            pending_embedding_count=0,
        )
        assert counts["chunks_not_in_faiss"] == 1  # sitemap 2 is in chunks (L2) but no FAISS vector

    def test_pending_embedding_passes_through_unchanged(self):
        counts = csc.compute_divergence(
            l1_ids=[], l2_ids=[], articles_ids=set(), chunks_l1_ids=[], chunks_l2_ids=[],
            pending_embedding_count=7,
        )
        assert counts["chunks_pending_embedding"] == 7

    def test_pure_no_shared_mutable_state_between_calls(self):
        ids = [1, 2]
        csc.compute_divergence(ids, ids, {1, 2}, ids, ids, 0)
        assert ids == [1, 2], "must not mutate its inputs"


class TestLoadDocstoreSitemapIds:
    def test_missing_index_returns_empty_list(self, tmp_path):
        assert csc._load_docstore_sitemap_ids(str(tmp_path / "nope")) == []

    def test_reads_sitemap_ids_from_a_real_pickle(self, tmp_path):
        docstore = SimpleNamespace(_dict={
            "uuid-1": SimpleNamespace(metadata={"sitemap_id": 5}),
            "uuid-2": SimpleNamespace(metadata={"sitemap_id": 9}),
            "uuid-3": SimpleNamespace(metadata={"other": "no sitemap_id key"}),
        })
        db_dir = tmp_path / "NEWS_L1"
        db_dir.mkdir()
        with open(db_dir / "index.pkl", "wb") as f:
            pickle.dump((docstore, {}), f)

        ids = csc._load_docstore_sitemap_ids(str(db_dir))
        assert sorted(ids) == [5, 9]


class TestFaissPairMismatch:
    """SYS-56 (#190): a level whose index.faiss and index.pkl are not one pair
    is a check, not something only load_index notices."""

    def _level(self, tmp_path, texts):
        from langchain_community.embeddings import FakeEmbeddings
        from langchain_community.vectorstores import FAISS
        from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
            ChunkFAISSDatasource)
        db = str(tmp_path / "NEWS_L2")
        vs = FAISS.from_texts(texts, FakeEmbeddings(size=8), metadatas=[{"sitemap_id": i} for i in range(len(texts))])
        index_generation.track_disk(vs, db)
        ChunkFAISSDatasource._atomic_save_local(vs, db)
        return db

    def test_a_whole_pair_has_no_problem(self, tmp_path):
        ids, problem = csc._read_level(self._level(tmp_path, ["a", "b"]))
        assert sorted(ids) == [0, 1] and problem is None

    def test_a_torn_pair_is_reported(self, tmp_path):
        import shutil
        other = self._level(tmp_path / "other", ["a", "b", "c"])
        db = self._level(tmp_path, ["a", "b"])
        shutil.copy2(os.path.join(other, "index.faiss"), os.path.join(db, "index.faiss"))
        ids, problem = csc._read_level(db)
        assert sorted(ids) == [0, 1]
        assert "3 vectors but index.pkl maps 2" in problem

    def test_a_missing_level_is_empty_and_fine(self, tmp_path):
        assert csc._read_level(str(tmp_path / "nope")) == ([], None)

    def test_the_count_is_a_check(self):
        counts = csc.compute_divergence(
            l1_ids=[1], l2_ids=[1], articles_ids={1}, chunks_l1_ids=[1], chunks_l2_ids=[1],
            pending_embedding_count=0, pair_mismatch_levels=1)
        assert csc.growing_checks(counts) == ["faiss_pair_mismatch"]


class TestReportingHelpers:
    def _counts(self, **overrides):
        base = {k: 0 for k in csc.CHECK_KEYS + csc.INFO_KEYS}
        base.update(overrides)
        return base

    def test_summary_all_zero_is_ok(self):
        line = csc.summary_line(self._counts())
        assert line.startswith("Store consistency: OK")

    def test_summary_known_debris_within_baseline_is_not_flagged_as_growing(self, monkeypatch):
        monkeypatch.setitem(csc.BASELINE, "l1_no_chunks", 5)
        line = csc.summary_line(self._counts(l1_no_chunks=5))
        assert "nonzero" in line
        assert "GROWING" not in line

    def test_summary_exceeding_baseline_is_flagged_growing(self):
        line = csc.summary_line(self._counts(l1_no_articles_terminal=1))
        assert "GROWING" in line and "l1_no_articles_terminal" in line

    def test_queued_sitemaps_alone_are_ok(self):
        line = csc.summary_line(self._counts(l1_no_articles_queued=5292, l2_no_articles_queued=5292))
        assert line.startswith("Store consistency: OK")

    def test_render_table_has_header_and_status_column(self):
        table = csc.render_table(self._counts(chunks_not_in_faiss=3))
        assert "CHECK" in table and "STATUS" in table
        assert "GROWING" in table  # chunks_not_in_faiss baseline is 0, so any count exceeds it

    def test_write_report_produces_valid_json(self, tmp_path):
        path = csc.write_report(self._counts(), str(tmp_path))
        assert os.path.exists(path)
        import json
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["counts"]["l1_total"] == 0
        assert payload["summary"].startswith("Store consistency: OK")


class _Stores:
    """A stand-in for the five queries gather_counts() makes, over a model of
    the tables. Any other SQL fails the test, so a changed query (SRC-53's check
    turned into `WHERE false`, say) cannot quietly return a default."""

    def __init__(self, sitemap_categories):
        self.categories = sitemap_categories

    def get_session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        q = " ".join(str(sql).split())
        if q == "SELECT DISTINCT sitemap_id FROM articles":
            return []
        if q.startswith("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = "):
            return []
        if q == "SELECT COUNT(*) FROM chunks WHERE chunk_status = 'pending_embedding'":
            return SimpleNamespace(scalar=lambda: 0)
        if q == "SELECT COUNT(*) FROM sitemaps WHERE category LIKE 'http%'":
            n = sum(1 for c in self.categories if c.startswith("http"))
            return SimpleNamespace(scalar=lambda: n)
        if q == "SELECT COUNT(*) FROM chunks WHERE chunk_level = 2 AND token_count > :m":
            assert params == {"m": 80}, "SYS-137: measured against CHUNK_MAX_TOKENS"
            return SimpleNamespace(scalar=lambda: 0)
        raise AssertionError("gather_counts sent SQL this model does not know: %s" % q)


class TestGatherCounts:
    """DBT-45 (#187): the I/O half. The integration twin
    (test_check_store_consistency_live.py) runs the same SQL on Postgres."""

    def test_a_stored_url_category_reaches_the_report(self, tmp_path, monkeypatch):
        import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
        monkeypatch.setattr(csc, "VECTOR_DB_NAME_L1", str(tmp_path / "NEWS_L1"))
        monkeypatch.setattr(csc, "VECTOR_DB_NAME_L2", str(tmp_path / "NEWS_L2"))
        stores = _Stores(["ekonomi", "https://www.inews.id/sitemap/news.xml", "nasional"])
        monkeypatch.setattr(sac, "SQLAlchemyClient", lambda: stores)
        counts = csc.gather_counts()
        assert counts["sitemaps_url_category"] == 1
        assert csc.growing_checks(counts) == ["sitemaps_url_category"]

    def test_a_torn_level_reaches_the_report(self, tmp_path, monkeypatch):
        """SYS-56 (#190): the pair check is part of the run's store check."""
        import newscrawler.infrastructure.network.clients.sqlalchemy_client as sac
        from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
        l2 = str(tmp_path / "NEWS_L2")
        monkeypatch.setattr(csc, "VECTOR_DB_NAME_L1", str(tmp_path / "NEWS_L1"))
        monkeypatch.setattr(csc, "VECTOR_DB_NAME_L2", l2)
        os.makedirs(index_generation.journal_dir(l2))  # a save killed after its commit point
        monkeypatch.setattr(sac, "SQLAlchemyClient", lambda: _Stores([]))
        counts = csc.gather_counts()
        assert counts["faiss_pair_mismatch"] == 1
        assert csc.growing_checks(counts) == ["faiss_pair_mismatch"]
