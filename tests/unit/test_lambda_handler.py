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
