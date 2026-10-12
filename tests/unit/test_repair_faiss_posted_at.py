"""SYS-91 (#257): the pure parts of scripts/repair_faiss_posted_at.py. The write path against a real
database and a temp FAISS pair is tests/integration/test_repair_faiss_posted_at_live.py."""
import importlib.util
import os

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "scripts", "repair_faiss_posted_at.py")


@pytest.fixture(scope="module")
def repair():
    spec = importlib.util.spec_from_file_location("repair_faiss_posted_at_unit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _meta(sid, posted_at, source="CNBC"):
    return {"sitemap_id": sid, "posted_at": posted_at, "source": source}


class TestSelectTargets:
    STORED = {1: 20260918, 2: 20260920, 3: 20260921}

    def test_a_1970_document_gets_its_sitemaps_date(self, repair):
        assert repair.select_targets([("d1", _meta(1, "19700823"))], self.STORED) == [
            ("d1", 1, "19700823", "20260918", "19xx", "CNBC")]

    def test_an_agreeing_document_is_not_a_target(self, repair):
        assert repair.select_targets([("d2", _meta(2, "20260920"))], self.STORED) == []

    def test_kinds(self, repair):
        docs = [("e", _meta(1, "")), ("o", _meta(2, "20260101")), ("n", _meta(3, None))]
        assert [t[4] for t in repair.select_targets(docs, self.STORED)] == ["empty", "other", "empty"]

    def test_a_document_whose_sitemap_is_gone_or_undated_is_left_alone(self, repair):
        docs = [("g", _meta(99, "19700823")), ("u", _meta(None, "19700823"))]
        assert repair.select_targets(docs, {**self.STORED, 99: None}) == []

    def test_a_string_sitemap_id_is_matched(self, repair):
        """FAISS metadata written by older code may hold the id as text."""
        assert [t[0] for t in repair.select_targets([("d", _meta("1", "19700823"))], self.STORED)] == ["d"]


class TestToWrite:
    MISMATCHES = [("a", 1, "19700823", "20260918", "19xx", "CNBC"),
                  ("b", 2, "20260101", "20260920", "other", "CNBC"),
                  ("c", 3, "", "20260921", "empty", "KOMPAS")]

    def test_only_the_1970_documents_by_default(self, repair):
        assert [t[0] for t in repair.to_write(self.MISMATCHES)] == ["a"]

    def test_every_kind_when_widened(self, repair):
        assert [t[0] for t in repair.to_write(self.MISMATCHES, only_1970=False)] == ["a", "b", "c"]

    def test_the_report_counts_every_kind_and_what_would_be_written(self, repair):
        text = repair.report({"NEWS_L1": self.MISMATCHES}, only_1970=True)
        assert "NEWS_L1: 3 document(s) whose posted_at differs" in text
        assert "1 would be rewritten (19xx only)" in text
        assert "'19xx': 1" in text and "'other': 1" in text and "'empty': 1" in text
