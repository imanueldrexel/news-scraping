"""
Unit tests for scripts/backfill_missing_articles.py drain_website loop logic.

drain_website must:
  - stop as soon as the article-less queue is empty,
  - call crawl_newsdetails once per non-empty pass,
  - stop early (not loop forever) if crawl_newsdetails raises,
  - respect the max-passes safety cap.
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "backfill_missing_articles.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_missing_articles", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["backfill_missing_articles.py"]  # guard argparse at import time
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


backfill = _load_module()


class TestDrainWebsite:
    def test_stops_when_queue_empty_immediately(self):
        repo = MagicMock()
        repo.load_sitemap_data.return_value = []  # nothing to do
        service = MagicMock()

        backfill.drain_website(service, repo, "WARTAEKONOMI", max_passes=10)

        service.crawl_newsdetails.assert_not_called()

    def test_loops_until_queue_drains(self):
        repo = MagicMock()
        # non-empty, non-empty, then empty
        repo.load_sitemap_data.side_effect = [["x"], ["x"], []]
        service = MagicMock()

        backfill.drain_website(service, repo, "WARTAEKONOMI", max_passes=10)

        assert service.crawl_newsdetails.call_count == 2
        service.crawl_newsdetails.assert_called_with("WARTAEKONOMI")

    def test_respects_max_passes_cap(self):
        repo = MagicMock()
        repo.load_sitemap_data.return_value = ["x"]  # never drains
        service = MagicMock()

        backfill.drain_website(service, repo, "WARTAEKONOMI", max_passes=3)

        assert service.crawl_newsdetails.call_count == 3

    def test_stops_on_crawl_exception(self):
        repo = MagicMock()
        repo.load_sitemap_data.return_value = ["x"]
        service = MagicMock()
        service.crawl_newsdetails.side_effect = RuntimeError("boom")

        backfill.drain_website(service, repo, "WARTAEKONOMI", max_passes=10)

        # Must not loop forever: one attempt, then bail out.
        assert service.crawl_newsdetails.call_count == 1


class TestDefaults:
    def test_default_websites_includes_wartaekonomi(self):
        assert "WARTAEKONOMI" in backfill.DEFAULT_WEBSITES
        assert len(backfill.DEFAULT_WEBSITES) >= 30
