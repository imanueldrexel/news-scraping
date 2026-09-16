"""
SYS-12: CrawlerAPI.crawl_websites_in_batch must isolate failures per source.
One source raising must not skip the sources after it, and the failure must
still be surfaced at the end so the run can exit non-zero.
"""
from unittest.mock import MagicMock

import pytest

from newscrawler.application.api.crawler_api import CrawlerAPI


def _api_raising_on(bad_sources, task_method="crawl_sitemaps"):
    svc = MagicMock()
    calls = []

    def side_effect(website_name, **kwargs):
        calls.append(website_name)
        if website_name in bad_sources:
            raise RuntimeError(f"simulated failure in {website_name}")
        return []

    getattr(svc, task_method).side_effect = side_effect
    return CrawlerAPI(svc), calls


SOURCES = ["BERITASATU", "CNBC", "CNN", "DETIK", "EMITENNEWS"]


class TestBatchIsolation:
    def test_BI01_first_source_failing_does_not_skip_the_rest(self):
        api, calls = _api_raising_on({"BERITASATU"})
        with pytest.raises(RuntimeError):
            api.crawl_websites_in_batch(SOURCES, task="sitemap")
        assert calls == SOURCES  # all five attempted

    def test_BI02_failure_is_still_surfaced_after_the_loop(self):
        api, _ = _api_raising_on({"CNN"})
        with pytest.raises(RuntimeError, match=r"1 of 5 sources failed: CNN"):
            api.crawl_websites_in_batch(SOURCES, task="sitemap")

    def test_BI03_multiple_failures_are_all_listed(self):
        api, calls = _api_raising_on({"BERITASATU", "DETIK"})
        with pytest.raises(RuntimeError, match=r"2 of 5 sources failed") as exc:
            api.crawl_websites_in_batch(SOURCES, task="sitemap")
        assert "BERITASATU" in str(exc.value) and "DETIK" in str(exc.value)
        assert calls == SOURCES

    def test_BI04_no_failures_returns_normally(self):
        api, calls = _api_raising_on(set())
        api.crawl_websites_in_batch(SOURCES, task="sitemap")
        assert calls == SOURCES

    def test_BI05_failure_in_full_text_task_is_isolated_too(self):
        api, calls = _api_raising_on({"CNBC"}, task_method="crawl_newsdetails")
        with pytest.raises(RuntimeError):
            api.crawl_websites_in_batch(SOURCES, task="full_text")
        assert calls == SOURCES

    def test_BI06_summary_line_logged_with_failed_sources(self, caplog):
        import logging
        api, _ = _api_raising_on({"CNN"})
        with caplog.at_level(logging.INFO, logger="newscrawler.application.api.crawler_api"):
            with pytest.raises(RuntimeError):
                api.crawl_websites_in_batch(SOURCES, task="sitemap")
        summary = [r.message for r in caplog.records if "Batch 'sitemap' finished" in r.message]
        assert summary and "ok=4 failed=1" in summary[0] and "CNN" in summary[0]

    def test_BI07_website_agnostic_tasks_unchanged(self):
        svc = MagicMock()
        api = CrawlerAPI(svc)
        api.crawl_websites_in_batch([], task="extract_knowledge")
        svc.extract_knowledge.assert_called_once()
        api.crawl_websites_in_batch([], task="newsletter")
        svc.generate_newsletter.assert_called_once()
