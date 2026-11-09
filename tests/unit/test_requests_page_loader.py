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


# ── SYS-66 (#213): backoff between retries, and a dead host named apart ──────

import socket
import threading
import time
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from newscrawler.core.page_loader import requests_page_loader as rpl


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(rpl, "_sleep", calls.append)
    return calls


def _dns_error():
    err = requests.exceptions.ConnectionError("Max retries exceeded (Caused by NewConnectionError)")
    err.__cause__ = socket.gaierror(11001, "getaddrinfo failed")
    return err


def _response(status, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    return r


class TestBackoff:
    def test_retries_sleep_with_exponential_backoff(self, loader, sleeps, monkeypatch):
        monkeypatch.setattr(rpl.random, "uniform", lambda a, b: 1.0)  # no jitter
        with patch.object(rpl.requests, "get", side_effect=requests.exceptions.ConnectionError("reset")):
            assert loader.get_url_with_reason("http://x") == (None, f"ConnectionError after {loader.max_retries} retries")
        expected = [min(rpl.REQUEST_RETRY_BACKOFF_MAX_S, rpl.REQUEST_RETRY_BACKOFF_S * 2 ** i)
                    for i in range(loader.max_retries)]
        assert sleeps == expected and expected == sorted(expected) and expected[0] > 0

    def test_backoff_is_capped(self, loader, monkeypatch):
        monkeypatch.setattr(rpl.random, "uniform", lambda a, b: 1.0)
        assert loader._backoff(10) == rpl.REQUEST_RETRY_BACKOFF_MAX_S

    def test_no_sleep_before_the_first_attempt_or_after_a_success(self, loader, sleeps):
        with patch.object(rpl.requests, "get", return_value=_response(200)):
            loader.get_url_with_reason("http://x")
        assert sleeps == []

    def test_a_host_that_does_not_resolve_is_named_so(self, loader):
        with patch.object(rpl.requests, "get", side_effect=_dns_error()):
            _, reason = loader.get_url_with_reason("http://gone.example")
        assert reason == f"NameResolutionError after {loader.max_retries} retries"

    def test_a_refused_connection_keeps_its_name(self, loader):
        err = requests.exceptions.ConnectionError("refused")
        err.__cause__ = ConnectionRefusedError(10061, "refused")
        with patch.object(rpl.requests, "get", side_effect=err):
            _, reason = loader.get_url_with_reason("http://x")
        assert reason == f"ConnectionError after {loader.max_retries} retries"


# ── SYS-70 (#218): identity, per-host pacing, Retry-After ───────────────────

class TestIdentity:
    def test_the_bot_user_agent_is_sent_by_default(self, loader):
        with patch.object(rpl.requests, "get", return_value=_response(200)) as get:
            loader.get_url("https://www.kompas.com/a")
        assert get.call_args.kwargs["headers"]["User-Agent"].startswith("NewsAggregatorBot/")

    @pytest.mark.parametrize("url", ["https://www.beritasatu.com/a", "https://investor.id/a",
                                     "https://www.tribunnews.com/a", "https://jakarta.tribunnews.com/a"])
    def test_hosts_that_refuse_the_bot_get_the_browser_user_agent(self, loader, url):
        assert loader.headers_for(url)["User-Agent"] == rpl.BROWSER_USER_AGENT

    def test_a_lookalike_host_is_not_matched(self, loader):
        assert loader.headers_for("https://notinvestor.id/a")["User-Agent"].startswith("NewsAggregatorBot/")


class TestHostGate:
    def test_request_starts_are_spaced_by_the_interval(self, monkeypatch, sleeps):
        monkeypatch.setattr(rpl, "_monotonic", lambda: 100.0)   # no time passes
        gate = rpl.HostGate(min_interval=1.0)
        for _ in range(3):
            with gate.slot():
                pass
        assert sleeps == [1.0, 2.0]

    def test_defer_pauses_the_next_start(self, monkeypatch, sleeps):
        monkeypatch.setattr(rpl, "_monotonic", lambda: 50.0)
        gate = rpl.HostGate()
        gate.defer(7.0)
        with gate.slot():
            pass
        assert sleeps == [7.0]

    def test_at_most_n_requests_are_in_flight(self):
        gate = rpl.HostGate(max_concurrency=2)
        inflight, peak, lock = [0], [0], threading.Lock()

        def work():
            with gate.slot():
                with lock:
                    inflight[0] += 1
                    peak[0] = max(peak[0], inflight[0])
                time.sleep(0.02)
                with lock:
                    inflight[0] -= 1

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert peak[0] == 2

    def test_a_configured_suffix_shares_one_gate_across_subdomains(self, loader):
        assert loader.min_intervals.get("kumparan.com") == 1.0
        assert loader.gate_for("https://kumparan.com/a") is loader.gate_for("https://m.kumparan.com/b")
        assert loader.gate_for("https://kumparan.com/a").min_interval == 1.0

    def test_an_unconfigured_host_is_not_paced(self, loader):
        assert loader.gate_for("https://www.kompas.com/a").min_interval == 0.0

    def test_every_attempt_goes_through_the_gate(self, loader):
        gate = MagicMock()
        loader.gate_for = lambda url: gate
        with patch.object(rpl.requests, "get", side_effect=[requests.exceptions.ConnectionError("x"), _response(200)]):
            loader.get_url("http://x")
        assert gate.slot.call_count == 2


class TestRetryAfter:
    def test_a_short_retry_after_is_waited_out_once_then_retried(self, loader, sleeps, monkeypatch):
        monkeypatch.setattr(rpl, "_monotonic", lambda: 0.0)
        ok = _response(200)
        with patch.object(rpl.requests, "get", side_effect=[_response(429, {"Retry-After": "5"}), ok]) as get:
            response, reason = loader.get_url_with_reason("http://x")
        assert response is ok and reason is None and get.call_count == 2
        assert 5.0 in sleeps

    def test_a_second_429_is_returned_not_waited_again(self, loader):
        second = _response(429, {"Retry-After": "5"})
        with patch.object(rpl.requests, "get", side_effect=[_response(429, {"Retry-After": "5"}), second]) as get:
            response, _ = loader.get_url_with_reason("http://x")
        assert response is second and get.call_count == 2

    def test_a_retry_after_longer_than_the_cap_is_not_waited(self, loader):
        r = _response(503, {"Retry-After": str(int(rpl.REQUEST_RETRY_AFTER_MAX_S) + 1)})
        with patch.object(rpl.requests, "get", return_value=r) as get:
            response, _ = loader.get_url_with_reason("http://x")
        assert response is r and get.call_count == 1

    def test_a_429_without_retry_after_is_returned_as_is(self, loader):
        r = _response(429)
        with patch.object(rpl.requests, "get", return_value=r) as get:
            assert loader.get_url_with_reason("http://x") == (r, None)
        assert get.call_count == 1

    def test_retry_after_as_an_http_date(self):
        now = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
        assert rpl.retry_after_seconds(format_datetime(now + timedelta(seconds=30)), now=now) == 30.0
        assert rpl.retry_after_seconds("not a date") is None
        assert rpl.retry_after_seconds(None) is None
