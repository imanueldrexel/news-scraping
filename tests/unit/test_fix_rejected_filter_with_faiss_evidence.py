"""
DBT-20 step 1: find_misclassified must ask the DB exactly "rejected_filter AND has an
L1 vector" (optionally scoped to one source), and load_l1_sitemap_ids must read the
FAISS docstore the same way check_store_consistency.py does.
"""
import importlib.util
import os
import pickle
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "fix_rejected_filter_with_faiss_evidence.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("fix_rejected_filter_with_faiss_evidence", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["fix_rejected_filter_with_faiss_evidence.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


fix = _load()


class TestLoadL1SitemapIds:
    def test_reads_sitemap_ids_from_the_l1_docstore(self, tmp_path, monkeypatch):
        docstore = SimpleNamespace(_dict={
            "uuid-1": SimpleNamespace(metadata={"sitemap_id": 10}),
            "uuid-2": SimpleNamespace(metadata={"sitemap_id": 20}),
        })
        with open(tmp_path / "index.pkl", "wb") as f:
            pickle.dump((docstore, {}), f)
        monkeypatch.setattr(fix, "VECTOR_DB_NAME_L1", str(tmp_path))

        assert fix.load_l1_sitemap_ids() == {10, 20}


class TestFindMisclassified:
    def test_passes_the_l1_ids_and_website_filter_to_the_query(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = [
            SimpleNamespace(sitemap_id=1, sources="MEDIAINDONESIA"),
            SimpleNamespace(sitemap_id=2, sources="MEDIAINDONESIA"),
        ]

        result = fix.find_misclassified(session, {1, 2, 3}, website="MEDIAINDONESIA")

        assert result == [(1, "MEDIAINDONESIA"), (2, "MEDIAINDONESIA")]
        sql, params = session.execute.call_args[0]
        assert "rejected_filter" in str(sql)
        # DBT-25: passing :ids is not the same as USING it -- the query must
        # restrict on the L1 set, or the script flips every rejected_filter row.
        # tests/integration/test_fix_rejected_filter_live.py proves it on a real table.
        assert "sitemap_id = ANY(:ids)" in str(sql)
        assert sorted(params["ids"]) == [1, 2, 3]
        assert params["website"] == "MEDIAINDONESIA"

    def test_website_none_means_no_source_filter(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []

        fix.find_misclassified(session, {5}, website=None)

        params = session.execute.call_args[0][1]
        assert params["website"] is None

    def test_empty_result_is_an_empty_list(self):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []

        assert fix.find_misclassified(session, {1}) == []
