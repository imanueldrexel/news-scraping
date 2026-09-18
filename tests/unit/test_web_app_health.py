"""
OPS-04: /api/health's faiss_docs field. Reads doc counts straight off each FAISS
index's pickle (same technique as check_store_consistency.py), never through
ChunkFAISSDatasource -- that would force the ~10s embedding-model/index load DBT-15
flags as a blocking hazard on every health check, not just the first query.
"""
import os
import pickle
from types import SimpleNamespace
from unittest.mock import patch

import newscrawler.web.app as app_mod


def _write_index_pkl(dir_path, doc_count):
    os.makedirs(dir_path, exist_ok=True)
    docstore = SimpleNamespace(_dict={f"uuid-{i}": SimpleNamespace(metadata={}) for i in range(doc_count)})
    with open(os.path.join(dir_path, "index.pkl"), "wb") as f:
        pickle.dump((docstore, {}), f)


class TestFaissDocCounts:
    def test_reads_both_index_doc_counts(self, tmp_path):
        l1_dir, l2_dir = str(tmp_path / "L1"), str(tmp_path / "L2")
        _write_index_pkl(l1_dir, 3)
        _write_index_pkl(l2_dir, 11)

        with patch("newscrawler.core.constants.VECTOR_DB_NAME_L1", l1_dir), \
             patch("newscrawler.core.constants.VECTOR_DB_NAME_L2", l2_dir):
            counts = app_mod._faiss_doc_counts()

        assert counts == {"NEWS_L1": 3, "NEWS_L2": 11}

    def test_missing_index_reports_none_not_an_exception(self, tmp_path):
        with patch("newscrawler.core.constants.VECTOR_DB_NAME_L1", str(tmp_path / "nope1")), \
             patch("newscrawler.core.constants.VECTOR_DB_NAME_L2", str(tmp_path / "nope2")):
            counts = app_mod._faiss_doc_counts()  # must not raise

        assert counts == {"NEWS_L1": None, "NEWS_L2": None}

    def test_one_index_missing_does_not_block_the_other(self, tmp_path):
        l1_dir = str(tmp_path / "L1")
        _write_index_pkl(l1_dir, 5)

        with patch("newscrawler.core.constants.VECTOR_DB_NAME_L1", l1_dir), \
             patch("newscrawler.core.constants.VECTOR_DB_NAME_L2", str(tmp_path / "nope")):
            counts = app_mod._faiss_doc_counts()

        assert counts == {"NEWS_L1": 5, "NEWS_L2": None}
