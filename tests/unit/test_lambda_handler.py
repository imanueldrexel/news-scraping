"""
SYS-06: process_event must not swallow a failed run. It used to catch
BaseException, log at INFO, and return normally, so Task Scheduler / cron
always saw exit 0 regardless of what happened underneath.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from newscrawler.application.api.lambda_function import lambda_handler


def _patched(side_effect):
    """Patch init_crawler so crawl_websites_in_batch raises side_effect."""
    api = MagicMock()
    api.crawl_websites_in_batch.side_effect = side_effect
    return patch.object(lambda_handler, "init_crawler", return_value=api)


class TestProcessEventFailurePropagation:
    def test_LH01_a_failed_batch_reraises_instead_of_returning_normally(self):
        with _patched(RuntimeError("2 of 5 sources failed: CNN, BERITASATU")):
            with pytest.raises(RuntimeError, match="2 of 5 sources failed"):
                lambda_handler.process_event({"task": "sitemap", "website": "CNN,BERITASATU"}, None)

    def test_LH02_failure_is_logged_at_error_with_traceback(self, caplog):
        with _patched(RuntimeError("boom")):
            with caplog.at_level(logging.ERROR, logger="newscrawler.application.api.lambda_function.lambda_handler"):
                with pytest.raises(RuntimeError):
                    lambda_handler.process_event({"task": "sitemap", "website": "CNN"}, None)
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert errors and "Failed to process task 'sitemap'" in errors[0].message
        assert errors[0].exc_info is not None  # logger.exception captured the traceback

    def test_LH03_keyboard_interrupt_is_not_caught_or_logged(self, caplog):
        with _patched(KeyboardInterrupt()):
            with caplog.at_level(logging.ERROR, logger="newscrawler.application.api.lambda_function.lambda_handler"):
                with pytest.raises(KeyboardInterrupt):
                    lambda_handler.process_event({"task": "sitemap", "website": "CNN"}, None)
        assert not any(r.levelno == logging.ERROR for r in caplog.records)

    def test_LH04_a_successful_batch_returns_normally(self):
        with _patched(None):
            lambda_handler.process_event({"task": "sitemap", "website": "CNN"}, None)  # no raise


class TestProcessEventValidatesBeforeTheModelLoad:
    """OPS-24 (#167): `init_crawler()` loads the models and both FAISS indexes
    (~2 min, ~4 GB). A typo must be rejected before that, not after."""

    def test_an_unknown_name_raises_without_calling_init_crawler(self):
        from unittest.mock import patch
        from newscrawler.application.api.lambda_function import lambda_handler
        with patch.object(lambda_handler, "init_crawler",
                          side_effect=AssertionError("init_crawler ran before validation")) as init:
            with pytest.raises(ValueError, match="KOMPASS"):
                lambda_handler.process_event({"task": "sitemap", "website": "KOMPASS"}, None)
        init.assert_not_called()

    def test_a_known_name_still_builds_and_dispatches(self):
        from unittest.mock import MagicMock, patch
        from newscrawler.application.api.lambda_function import lambda_handler
        api = MagicMock()
        with patch.object(lambda_handler, "init_crawler", return_value=api):
            lambda_handler.process_event({"task": "sitemap", "website": "KOMPAS, CNBC"}, None)
        api.crawl_websites_in_batch.assert_called_once_with(website_names=["KOMPAS", "CNBC"], task="sitemap",
                                                         target_date=None)


class TestRefusesUnderTheRunLock:
    """DBT-43 (#183): a manual full_text/all crawl is refused before init_crawler
    (the model and FAISS load) while a scheduled crawl holds the run lock."""

    @pytest.fixture
    def held(self):
        """The lock held by a live process that is neither us nor our parent
        (a parent holder would make us its worker, which may write)."""
        import json, subprocess, sys, psutil
        from newscrawler.tools import run_lock
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            with open(run_lock.LOCK_PATH, "w", encoding="utf-8") as f:
                json.dump({"pid": p.pid, "create_time": psutil.Process(p.pid).create_time(),
                           "started_at": "2026-09-27T00:00:00+00:00"}, f)
            yield
        finally:
            p.kill()
            p.wait()

    @pytest.mark.parametrize("task", ["full_text", "all"])
    def test_a_faiss_writing_task_is_refused_before_the_model_load(self, task, held):
        from newscrawler.tools.run_lock import RunLockHeld
        with patch.object(lambda_handler, "init_crawler") as init:
            with pytest.raises(RunLockHeld):
                lambda_handler.process_event({"task": task, "website": "CNN"}, None)
        init.assert_not_called()

    def test_a_sitemap_crawl_still_runs(self, held):
        with _patched(None) as init:
            lambda_handler.process_event({"task": "sitemap", "website": "CNN"}, None)
        init.assert_called_once()
