"""SYS-35 (#118, fix 2): the re-queue selects rejected_filter rows by the live
filter's own is_finance_category() -- finance sections only, never the general
buckets (those are SYS-38's), never a soft vertical."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from requeue_finance_rejects import _CANDIDATES_SQL, _REQUEUE_SQL, find_finance_rejects  # noqa: E402


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.params = None

    def execute(self, _sql, params=None):
        self.params = params
        return SimpleNamespace(fetchall=lambda: self._rows)


def _row(sitemap_id, sources, category):
    return SimpleNamespace(sitemap_id=sitemap_id, sources=sources, category=category,
                           last_crawl_attempt=None, fetch_failures=0)


class TestFindFinanceRejects:
    def test_only_finance_section_rows_are_selected(self):
        session = _Session([
            _row(1, "LIPUTAN6", "bisnis"),
            _row(2, "MERDEKA", "uang"),
            _row(3, "ANTARANEWS", "Ekonomi"),
            _row(4, "WARTAEKONOMI", "energi"),
            _row(5, "KOMPAS", "nasional"),      # hard news, not finance -> SYS-38
            _row(6, "CNBC", "news"),            # mixed bucket -> SYS-38
            _row(7, "IDNTIMES", "hype"),        # soft -> stays rejected
            _row(8, "JPNN", "bali/politik"),    # hard news -> SYS-38
            _row(9, "INEWS", "finance/keuangan"),
        ])
        targets, by_key = find_finance_rejects(session)
        assert targets == [1, 2, 3, 4, 9]
        assert by_key == {
            ("LIPUTAN6", "bisnis"): 1, ("MERDEKA", "uang"): 1, ("ANTARANEWS", "Ekonomi"): 1,
            ("WARTAEKONOMI", "energi"): 1, ("INEWS", "finance/keuangan"): 1,
        }
        assert session.params == {"websites": None}

    def test_website_filter_is_passed_to_the_query(self):
        session = _Session([])
        find_finance_rejects(session, ["LIPUTAN6", "SUARA"])
        assert session.params == {"websites": ["LIPUTAN6", "SUARA"]}

    def test_candidates_sql_excludes_rows_that_already_have_an_article(self):
        """DBT-32 (#141): a `rejected_filter` row with an articles row is a
        SYS-16 backfill misclassification (DBT-26's shape), not a recall loss;
        flipping it to `pending` would re-fetch it into a second save attempt.
        The SQL is the guard (the live proof is in
        tests/integration/test_requeue_finance_rejects_live.py)."""
        sql = " ".join(str(_CANDIDATES_SQL).split())
        assert "crawl_status = 'rejected_filter'" in sql
        assert "NOT EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = sitemaps.sitemap_id)" in sql
        # And the UPDATE re-checks the status, so a row saved between the
        # SELECT and the UPDATE is not flipped.
        assert "crawl_status = 'rejected_filter'" in " ".join(str(_REQUEUE_SQL).split())
