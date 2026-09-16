"""
SYS-05: `except A or B` on two exception classes evaluates to `A` (a plain boolean
"is A truthy" check, not a tuple), so RequestsPageLoader.get_url only ever retried
requests.exceptions.ReadTimeout. A ConnectionError (reset, DNS failure, TLS handshake
failure) fell through to the generic `except BaseException` and got exactly one
attempt before returning None.
"""
from unittest.mock import patch

import pytest
import requests

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader


@pytest.fixture
def loader():
    return RequestsPageLoader()


class TestRetryOnConnectionError:
    def test_connection_error_is_retried_max_retries_plus_one_attempts(self, loader):
        with patch(
            "newscrawler.core.page_loader.requests_page_loader.requests.get",
            side_effect=requests.exceptions.ConnectionError("connection reset"),
        ) as mock_get:
            result = loader.get_url("http://x")

        assert result is None
        assert mock_get.call_count == loader.max_retries + 1

    def test_read_timeout_is_still_retried_max_retries_plus_one_attempts(self, loader):
        with patch(
            "newscrawler.core.page_loader.requests_page_loader.requests.get",
            side_effect=requests.exceptions.ReadTimeout("timed out"),
        ) as mock_get:
            result = loader.get_url("http://x")

        assert result is None
        assert mock_get.call_count == loader.max_retries + 1

    def test_connection_error_succeeding_on_a_later_attempt_returns_the_response(self, loader):
        good_response = object()
        with patch(
            "newscrawler.core.page_loader.requests_page_loader.requests.get",
            side_effect=[requests.exceptions.ConnectionError("reset"), good_response],
        ) as mock_get:
            result = loader.get_url("http://x")

        assert result is good_response
        assert mock_get.call_count == 2

    def test_a_mix_of_readtimeout_and_connectionerror_across_retries_is_all_retried(self, loader):
        errors = [
            requests.exceptions.ConnectionError("reset"),
            requests.exceptions.ReadTimeout("timed out"),
        ] * ((loader.max_retries + 1) // 2 + 1)
        with patch(
            "newscrawler.core.page_loader.requests_page_loader.requests.get",
            side_effect=errors[: loader.max_retries + 1],
        ) as mock_get:
            result = loader.get_url("http://x")

        # every attempt exhausts (initial + max_retries retries), alternating error
        # type each time -- proves neither exception type ever falls through to the
        # outer `except BaseException` mid-sequence.
        assert result is None
        assert mock_get.call_count == loader.max_retries + 1

    def test_other_exceptions_are_not_retried_at_all(self, loader):
        with patch(
            "newscrawler.core.page_loader.requests_page_loader.requests.get",
            side_effect=ValueError("not a requests exception"),
        ) as mock_get:
            result = loader.get_url("http://x")

        assert result is None
        assert mock_get.call_count == 1
