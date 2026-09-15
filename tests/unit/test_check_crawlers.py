"""
Unit tests for scripts/check_crawlers.py — classification + per-outlet check against a
mocked crawler (no network).
"""
import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "check_crawlers.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("check_crawlers", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["check_crawlers.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


cc = _load()


def _detail(text):
    return SimpleNamespace(extracted_text=text)


class TestClassify:
    def test_ok(self):
        assert cc.classify(sitemap_links=10, detail_ok=2) == cc.STATUS_OK

    def test_partial_when_no_extraction(self):
        assert cc.classify(sitemap_links=10, detail_ok=0) == cc.STATUS_PARTIAL

    def test_broken_when_no_links(self):
        assert cc.classify(sitemap_links=0, detail_ok=0) == cc.STATUS_BROKEN

    def test_error_flag(self):
        assert cc.classify(sitemap_links=10, detail_ok=2, error=True) == cc.STATUS_ERROR


class TestExtractedLen:
    def test_list(self):
        assert cc._extracted_len(_detail(["abc", "de"])) == 5

    def test_string(self):
        assert cc._extracted_len(_detail("hello")) == 5

    def test_empty(self):
        assert cc._extracted_len(_detail(None)) == 0
        assert cc._extracted_len(_detail([])) == 0


def _mock_crawler(soup="SOUP", branches=None, articles=None, dtos=None, details=None):
    c = MagicMock()
    c.website_url = "http://example.com/sitemap.xml"
    c.page_loader.get_soup.return_value = soup
    c._get_branches.return_value = branches if branches is not None else {"news": "http://e.com/news.xml"}
    c._scrape.return_value = articles if articles is not None else [{"link": "http://e.com/a"}]
    c.batch_crawling_sitemap.return_value = dtos if dtos is not None else [SitemapDTO(headline="h", link="http://e.com/a", sources="KOMPAS")]
    c.batch_crawling_details.return_value = details if details is not None else [_detail(["body text here"])]
    return c


class TestCheckOne:
    def test_happy_path_ok(self):
        r = cc.check_one("KOMPAS", _mock_crawler(), sample_size=2)
        assert r["status"] == cc.STATUS_OK
        assert r["sitemap_links"] == 1
        assert r["detail_ok"] == 1

    def test_partial_when_extraction_empty(self):
        c = _mock_crawler(details=[_detail([]), _detail("")])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_PARTIAL
        assert "extraction" in r["note"].lower()

    def test_broken_when_soup_none(self):
        c = _mock_crawler(soup=None)
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_broken_when_no_branches(self):
        c = _mock_crawler(branches={})
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_broken_when_no_links(self):
        c = _mock_crawler(articles=[])
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_BROKEN

    def test_error_when_method_raises(self):
        c = _mock_crawler()
        c._scrape.side_effect = RuntimeError("boom")
        r = cc.check_one("KOMPAS", c, sample_size=2)
        assert r["status"] == cc.STATUS_ERROR
        assert "RuntimeError" in r["note"]


class TestReportingHelpers:
    def test_summary_line_flags_unhealthy(self):
        results = [
            {"website": "KOMPAS", "status": cc.STATUS_OK, "note": ""},
            {"website": "DETIK", "status": cc.STATUS_PARTIAL, "note": "x"},
        ]
        line = cc.summary_line(results)
        assert "DETIK" in line and "OK=1" in line

    def test_render_table_has_header_and_rows(self):
        results = [{"website": "KOMPAS", "status": cc.STATUS_OK, "sitemap_links": 5,
                    "dto_count": 3, "detail_total": 3, "detail_ok": 3, "avg_chars": 900, "note": ""}]
        table = cc.render_table(results)
        assert "SOURCE" in table and "KOMPAS" in table
