"""
OPS-04 / OPS-14: /api/health's faiss_docs field.

OPS-04 added the field by unpickling both FAISS docstores (37 MB + 83 MB) on
every request, inside an async handler -- 2.1 s and 304 MB per call, on the event
loop, growing with the corpus (OPS-14, #80). The count now comes from the FAISS
index header via faiss.read_index(..., IO_FLAG_MMAP).ntotal, is cached on the
index file's (mtime, size), and the whole payload runs in the threadpool. These
tests pin all three: no pickle.load, no re-read on a warm cache, not on the
event-loop thread.
"""
import asyncio
import os
import threading
import time
from unittest.mock import patch

import faiss
import numpy as np

import newscrawler.web.app as app_mod


def _write_index_faiss(dir_path, vector_count, dim=4):
    """A real, tiny FAISS index with `vector_count` vectors -- what save_local
    writes as index.faiss. No index.pkl: the count must not need it."""
    os.makedirs(dir_path, exist_ok=True)
    index = faiss.IndexFlatL2(dim)
    if vector_count:
        index.add(np.random.default_rng(0).random((vector_count, dim), dtype="float32"))
    faiss.write_index(index, os.path.join(dir_path, "index.faiss"))


def _patched_dirs(l1_dir, l2_dir):
    return patch.multiple("newscrawler.core.constants", VECTOR_DB_NAME_L1=l1_dir, VECTOR_DB_NAME_L2=l2_dir)


class TestFaissDocCounts:
    def setup_method(self):
        app_mod._faiss_count_cache.clear()

    def test_reads_both_index_vector_counts(self, tmp_path):
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_faiss(l1_dir, 3)
        _write_index_faiss(l2_dir, 11)

        with _patched_dirs(l1_dir, l2_dir):
            counts = app_mod._faiss_doc_counts()

        assert counts == {"NEWS_L1": 3, "NEWS_L2": 11}

    def test_never_unpickles_the_docstore(self, tmp_path):
        """OPS-14's core guard: a docstore that cannot be unpickled must not matter,
        because the count has to come from the index header, not from index.pkl."""
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_faiss(l1_dir, 7)
        _write_index_faiss(l2_dir, 2)
        for d in (l1_dir, l2_dir):
            with open(os.path.join(d, "index.pkl"), "wb") as f:
                f.write(b"not a pickle")

        with _patched_dirs(l1_dir, l2_dir), \
             patch("pickle.load", side_effect=AssertionError("docstore was unpickled")):
            counts = app_mod._faiss_doc_counts()

        assert counts == {"NEWS_L1": 7, "NEWS_L2": 2}

    def test_missing_index_reports_none_not_an_exception(self, tmp_path):
        with _patched_dirs(str(tmp_path / "nope1"), str(tmp_path / "nope2")):
            counts = app_mod._faiss_doc_counts()  # must not raise

        assert counts == {"NEWS_L1": None, "NEWS_L2": None}

    def test_one_index_missing_does_not_block_the_other(self, tmp_path):
        l1_dir = str(tmp_path / "L1")
        _write_index_faiss(l1_dir, 5)

        with _patched_dirs(l1_dir, str(tmp_path / "nope")):
            counts = app_mod._faiss_doc_counts()

        assert counts == {"NEWS_L1": 5, "NEWS_L2": None}

    def test_warm_cache_does_not_reopen_the_index(self, tmp_path):
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_faiss(l1_dir, 3)
        _write_index_faiss(l2_dir, 4)

        with _patched_dirs(l1_dir, l2_dir):
            first = app_mod._faiss_doc_counts()
            with patch("faiss.read_index", side_effect=AssertionError("index re-read on a warm cache")):
                second = app_mod._faiss_doc_counts()

        assert first == second == {"NEWS_L1": 3, "NEWS_L2": 4}

    def test_a_rewritten_index_invalidates_the_cache(self, tmp_path):
        """The pipeline's save_local replaces index.faiss; the next health call must
        see the new count, not the cached one."""
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_faiss(l1_dir, 3)
        _write_index_faiss(l2_dir, 4)

        with _patched_dirs(l1_dir, l2_dir):
            assert app_mod._faiss_doc_counts() == {"NEWS_L1": 3, "NEWS_L2": 4}
            time.sleep(0.01)  # make sure mtime can move even on coarse filesystems
            _write_index_faiss(l2_dir, 9)
            assert app_mod._faiss_doc_counts() == {"NEWS_L1": 3, "NEWS_L2": 9}

    def test_count_matches_what_check_store_consistency_would_report(self, tmp_path):
        """ntotal is the number of vectors; for a LangChain FAISS store that is the
        docstore length check_store_consistency.py prints as 'total vectors'."""
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_faiss(l1_dir, 123)
        _write_index_faiss(l2_dir, 0)

        with _patched_dirs(l1_dir, l2_dir):
            counts = app_mod._faiss_doc_counts()

        assert counts["NEWS_L1"] == faiss.read_index(os.path.join(l1_dir, "index.faiss")).ntotal == 123
        assert counts["NEWS_L2"] == 0


class TestHealthRunsOffTheEventLoop:
    def test_payload_is_built_on_a_worker_thread(self):
        """OPS-14: the handler is `async def`; if the payload ran inline, every
        other request would stall for its duration. It must run in the threadpool."""
        seen = {}

        def fake_payload():
            seen["thread"] = threading.get_ident()
            return {"status": "ok"}

        with patch.object(app_mod, "_health_payload", fake_payload):
            result = asyncio.run(app_mod.api_health())

        assert result == {"status": "ok"}
        assert seen["thread"] != threading.get_ident()

    def test_payload_degrades_instead_of_raising_when_stats_fail(self):
        with patch.object(app_mod, "_get_stats_ds", side_effect=RuntimeError("db down")):
            result = app_mod._health_payload()

        assert result["status"] == "degraded"
        assert "db down" in result["error"]
