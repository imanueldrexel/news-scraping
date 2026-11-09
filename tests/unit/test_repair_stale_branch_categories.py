"""SRC-48 (#158): the repair's selection, which decides which production rows
get their `sitemaps.category` rewritten. Offline -- no DB, no network.

Filed as a test because an untested selection in a script that writes to
production is the DBT-27 (#88) / DBT-21 (#72) class: the run is the only thing
that ever exercises it.
"""
from types import SimpleNamespace

import pytest

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from scripts.repair_stale_branch_categories import plan


def _row(sid, category, link, crawl_status="pending"):
    return SimpleNamespace(sitemap_id=sid, category=category, link=link, crawl_status=crawl_status)


MI = "https://mediaindonesia.com"


class TestPlan:
    def _crawler(self):
        return CRAWLER_DICT["MEDIAINDONESIA"]

    def test_rewrites_a_branch_name_to_the_articles_own_section(self):
        rows = [_row(1, "news", f"{MI}/olahraga/936920/jorge-martin"),
                _row(2, "news", f"{MI}/ekonomi/936800/rupiah-menguat")]
        changes, unmappable = plan(rows, self._crawler())
        assert [(c[0], c[1], c[2]) for c in changes] == [(1, "news", "olahraga"), (2, "news", "ekonomi")]
        assert unmappable == []

    def test_leaves_a_row_that_already_holds_its_own_section(self):
        """Idempotency: a second run must find nothing."""
        rows = [_row(1, "olahraga", f"{MI}/olahraga/936920/jorge-martin"),
                _row(2, " ekonomi ", f"{MI}/ekonomi/1/x")]
        changes, _ = plan(rows, self._crawler())
        assert changes == []

    def test_reports_but_does_not_touch_a_link_it_cannot_name(self):
        rows = [_row(1, "news", f"{MI}/sitemap-news.xml"),
                _row(2, "news", "https://example.com/"),
                _row(3, "news", "")]
        changes, unmappable = plan(rows, self._crawler())
        assert changes == [], "an unnameable link must never be rewritten"
        assert [u[0] for u in unmappable] == [1, 2, 3]

    def test_never_writes_a_url_shaped_category(self):
        """The SRC-36/SRC-41 damage, and what MEDIAINDONESIA's old override
        produced. `usable_section_name` is the guard; this pins that the repair
        honours it rather than re-deriving its own rule."""
        crawler = self._crawler()
        rows = [_row(1, "news", f"{MI}/olahraga/1/x")]
        crawler_broken = type("Broken", (type(crawler),), {
            "_get_branch_name_from_url": staticmethod(lambda url: url)})()
        changes, unmappable = plan(rows, crawler_broken)
        assert changes == [] and len(unmappable) == 1

    def test_preserves_crawl_status_for_the_report(self):
        rows = [_row(1, "news", f"{MI}/olahraga/1/x", "saved"),
                _row(2, "news", f"{MI}/hiburan/1/x", "rejected_filter")]
        changes, _ = plan(rows, self._crawler())
        assert [c[3] for c in changes] == ["saved", "rejected_filter"]

    @pytest.mark.parametrize("section,gate", [
        ("olahraga", "deny"), ("sepak-bola", "deny"), ("hiburan", "deny"), ("opini", "deny"),
        ("ekonomi", "allow"), ("politik-dan-hukum", "allow"), ("nusantara", "allow"),
        ("humaniora", None), ("kesehatan", None),
    ])
    def test_the_repaired_values_gate_as_expected(self, section, gate):
        """What the repair is FOR: 198 rows moved from the mixed `news` bucket
        to a real deny, and 464 to a real allow."""
        from newscrawler.core.importance_filter import category_gate
        assert category_gate(section) == gate
        assert category_gate("news") is None
