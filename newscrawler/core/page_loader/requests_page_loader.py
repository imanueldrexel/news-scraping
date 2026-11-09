import logging
import random
import re
import socket
import threading
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

from bs4 import BeautifulSoup
from urllib.parse import urlparse

from newscrawler.core.constants import (
    BROWSER_UA_HOSTS, CRAWLER_CONTACT, CRAWLER_USER_AGENT, HOST_MAX_CONCURRENCY, HOST_MIN_INTERVAL_S,
    REQUEST_MAX_RETRIES, REQUEST_RETRY_AFTER_MAX_S, REQUEST_RETRY_BACKOFF_MAX_S, REQUEST_RETRY_BACKOFF_S,
)
from newscrawler.core.page_loader.page_loader import PageLoader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-14: a site can answer HTTP 200 for a missing article either by redirecting
# to an error/home page or by rendering the error page in place. Same pattern
# used by scripts/experiments/probe_soft404.py.
ERROR_PATH_PATTERN = re.compile(r"/(404|not-?found|error)(/|$|\?)", re.I)

# The browser identity the loader used for every source until SYS-70. Kept only
# for BROWSER_UA_HOSTS, the sources that refuse a bot UA.
BROWSER_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/56.0.2924.87 Safari/537.36")

# Patched by the tests.
_sleep = time.sleep
_monotonic = time.monotonic


def parse_host_values(raw: str, cast=float) -> Dict[str, float]:
    """'kumparan.com=1.0,detik.com=0.5' -> {'kumparan.com': 1.0, 'detik.com': 0.5}."""
    out = {}
    for part in (raw or "").split(","):
        if "=" in part:
            host, value = part.split("=", 1)
            if host.strip():
                out[host.strip().lower()] = cast(value)
    return out


def _host_suffix_match(host: str, suffixes) -> Optional[str]:
    """The configured suffix `host` falls under (exact, or a subdomain of it)."""
    host = (host or "").lower()
    for suffix in suffixes:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return None


# getaddrinfo's "this name does not exist" (NXDOMAIN): EAI_NONAME, which Windows reports as
# WSAHOST_NOT_FOUND (11001). Any other failure (EAI_AGAIN/WSATRY_AGAIN, a timeout) is not a fact
# about the host.
_NO_SUCH_HOST = frozenset(e for e in (getattr(socket, "EAI_NONAME", None), 11001) if e is not None)


def host_resolves(host: str) -> Optional[bool]:
    """SRC-58 (#231): True when `host` has an address, False when DNS says it
    does not exist, None when the lookup failed for another reason (no verdict).
    One lookup, no retries: a crawler asks before fetching a branch, so a dead
    regional subdomain is not retried with backoff on every run."""
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror as e:
        return False if e.errno in _NO_SUCH_HOST else None
    except (OSError, UnicodeError):
        return None


def is_name_resolution_failure(exc: BaseException) -> bool:
    """SYS-66: the host did not resolve. requests wraps it as
    ConnectionError -> MaxRetryError -> NewConnectionError -> socket.gaierror;
    a refused or reset connection has no gaierror in that chain."""
    seen = set()
    stack = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, socket.gaierror):
            return True
        stack.extend([e.__cause__, e.__context__, getattr(e, "reason", None)])
        stack.extend(a for a in getattr(e, "args", ()) if isinstance(a, BaseException))
    return False


def retry_after_seconds(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Retry-After is delta-seconds or an HTTP date; None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


class HostGate:
    """SYS-70 (#218): politeness toward one host, shared by every thread of one
    loader. Request starts are spaced at least `min_interval` apart, at most
    `max_concurrency` requests are in flight, and `defer` (a Retry-After)
    pauses the whole host, not just the request that got it."""

    def __init__(self, min_interval: float = 0.0, max_concurrency: Optional[int] = None):
        self.min_interval = max(0.0, float(min_interval or 0.0))
        self._slots = threading.BoundedSemaphore(max_concurrency) if max_concurrency else None
        self._lock = threading.Lock()
        self._next_start = 0.0

    def defer(self, seconds: float) -> None:
        with self._lock:
            self._next_start = max(self._next_start, _monotonic() + seconds)

    @contextmanager
    def slot(self):
        if self._slots is not None:
            self._slots.acquire()
        try:
            with self._lock:
                now = _monotonic()
                start = max(now, self._next_start)
                self._next_start = start + self.min_interval
            if start > now:
                _sleep(start - now)
            yield
        finally:
            if self._slots is not None:
                self._slots.release()


class RequestsPageLoader(PageLoader):
    def __init__(self):
        self.max_retries = REQUEST_MAX_RETRIES
        bot_ua = CRAWLER_USER_AGENT + (f" (+{CRAWLER_CONTACT})" if CRAWLER_CONTACT else "")
        self.headers = {
            "Accept-Encoding": "gzip, deflate, sdch",
            "Accept-Language": "en-US,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": bot_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }
        self.browser_ua_hosts = [h.strip().lower() for h in BROWSER_UA_HOSTS.split(",") if h.strip()]
        self.min_intervals = parse_host_values(HOST_MIN_INTERVAL_S, float)
        self.max_concurrency = parse_host_values(HOST_MAX_CONCURRENCY, int)
        self._gates: Dict[str, HostGate] = {}
        self._gates_lock = threading.Lock()

    def headers_for(self, url_path: str) -> dict:
        """SYS-70: the bot UA, except for the hosts that refuse it."""
        if _host_suffix_match(urlparse(url_path).hostname, self.browser_ua_hosts):
            return dict(self.headers, **{"User-Agent": BROWSER_USER_AGENT})
        return self.headers

    def gate_for(self, url_path: str) -> HostGate:
        """One gate per configured suffix (all of kumparan.com shares one), else
        per host (so a Retry-After pauses that host only)."""
        host = (urlparse(url_path).hostname or "").lower()
        key = (_host_suffix_match(host, self.min_intervals) or _host_suffix_match(host, self.max_concurrency)
               or host)
        with self._gates_lock:
            gate = self._gates.get(key)
            if gate is None:
                gate = HostGate(self.min_intervals.get(key, 0.0), self.max_concurrency.get(key))
                self._gates[key] = gate
            return gate

    def get_url(self, url_path):
        return self.get_url_with_reason(url_path)[0]

    def _backoff(self, retry_index: int) -> float:
        """SYS-66: base * 2**n with +-50% jitter, capped."""
        delay = min(REQUEST_RETRY_BACKOFF_MAX_S, REQUEST_RETRY_BACKOFF_S * (2 ** retry_index))
        return delay * random.uniform(0.5, 1.5)

    def get_url_with_reason(self, url_path):
        """(response, None) or (None, reason). OPS-15: the reason distinguishes a
        timeout/connection failure (after retries) from any other request error,
        so it can be stored per sitemap instead of a constant.

        SYS-66 (#213): retries sleep with exponential backoff, and a host that
        does not resolve is named `NameResolutionError after N retries` (a fact
        about the host) apart from a refused/reset connection or a timeout.
        SYS-70 (#218): every attempt goes through the host's gate, and a 429/503
        carrying a short Retry-After is waited out once."""
        headers = self.headers_for(url_path)
        gate = self.gate_for(url_path)
        last_err = None
        waited_retry_after = False
        attempt = 0
        while attempt <= self.max_retries:
            if attempt and last_err is not None:
                logger.info(f"Retry {attempt - 1} to connect")
                _sleep(self._backoff(attempt - 1))
            try:
                with gate.slot():
                    response = requests.get(url_path, headers=headers,
                                            timeout=(10, 27) if attempt == 0 else (20, 30), stream=True)
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as err:
                # SYS-05: both classes, as a tuple -- `A or B` caught only ReadTimeout.
                last_err = err
                attempt += 1
                continue
            except BaseException as e:
                logger.info(f"Failed to get {url_path}. Reason {e}, Returning None")
                return None, f"request failed: {type(e).__name__}: {e}"[:200]
            if getattr(response, "status_code", None) in (429, 503) and not waited_retry_after:
                delay = retry_after_seconds(response.headers.get("Retry-After"))
                if delay is not None and delay <= REQUEST_RETRY_AFTER_MAX_S:
                    logger.info(f"HTTP {response.status_code} with Retry-After {delay:.0f}s for {url_path}; "
                                f"pausing the host and retrying once")
                    response.close()
                    gate.defer(delay)
                    waited_retry_after = True
                    last_err = None
                    continue
            return response, None
        name = "NameResolutionError" if is_name_resolution_failure(last_err) else type(last_err).__name__
        return None, f"{name} after {self.max_retries} retries"

    def get_soup(self, url_path: str):
        return self.get_soup_with_reason(url_path)[0]

    def get_soup_with_reason(self, url_path: str):
        """(soup, None) on success, (None, reason) on failure -- see PageLoader."""
        response, reason = self.get_url_with_reason(url_path)
        if response is None:
            return None, reason
        if response.status_code == 200:
            # SYS-14: a 200 that was redirected to an error/home page is a soft-404,
            # not a real article -- reject it before it reaches the extractor chain.
            final_path = urlparse(response.url).path
            if response.history and ERROR_PATH_PATTERN.search(final_path):
                logger.info(
                    f"Failed to get {url_path}. Redirected to error page {response.url}, Returning None"
                )
                return None, f"soft-404: redirected to {response.url}"[:200]
            try:
                soup = BeautifulSoup(response.content, "html.parser")
            except BaseException as e:
                logger.info(
                    f"Failed to get the HTML for {url_path}. Reason: {e}, Returning None"
                )
                return None, f"HTML parse failed: {type(e).__name__}: {e}"[:200]

            # Some sites render the error page in place (no redirect) but still
            # mark it with a canonical link pointing at the real error/home page.
            canonical = soup.find("link", rel="canonical")
            canonical_href = canonical.get("href") if canonical else None
            if canonical_href and ERROR_PATH_PATTERN.search(urlparse(canonical_href).path):
                logger.info(
                    f"Failed to get {url_path}. Canonical points to error page {canonical_href}, Returning None"
                )
                return None, f"soft-404: canonical {canonical_href}"[:200]

            return soup, None
        logger.info(
            f"Failed to get {url_path}. Status Code: {response.status_code}, Returning None"
        )
        return None, f"HTTP {response.status_code}"
