import logging
import re
import requests

from bs4 import BeautifulSoup
from urllib.parse import urlparse

from newscrawler.core.constants import REQUEST_MAX_RETRIES
from newscrawler.core.page_loader.page_loader import PageLoader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-14: a site can answer HTTP 200 for a missing article either by redirecting
# to an error/home page or by rendering the error page in place. Same pattern
# used by scripts/experiments/probe_soft404.py.
ERROR_PATH_PATTERN = re.compile(r"/(404|not-?found|error)(/|$|\?)", re.I)


class RequestsPageLoader(PageLoader):
    def __init__(self):
        self.max_retries = REQUEST_MAX_RETRIES
        self.headers = {
            "Accept-Encoding": "gzip, deflate, sdch",
            "Accept-Language": "en-US,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 "
            "Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

    def get_url(self, url_path):
        return self.get_url_with_reason(url_path)[0]

    def get_url_with_reason(self, url_path):
        """(response, None) or (None, reason). OPS-15: the reason distinguishes a
        timeout/connection failure (after retries) from any other request error,
        so it can be stored per sitemap instead of a constant."""
        try:
            response = requests.get(
                url_path, headers=self.headers, timeout=(10, 27), stream=True
            )
            return response, None
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as first_err:
            # SYS-05: `A or B` on two exception classes evaluates to `A`, so this
            # used to catch only ReadTimeout -- a ConnectionError (reset, DNS, TLS)
            # fell straight through to the generic `except BaseException` below and
            # got exactly one attempt instead of being retried.
            last_err = first_err
            for idx in range(self.max_retries):
                logger.info(f"Retry {idx} to connect")
                try:
                    response = requests.get(
                        url_path, headers=self.headers, timeout=(20, 30)
                    )
                    return response, None
                except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as retry_err:
                    last_err = retry_err
                    continue
            return None, f"{type(last_err).__name__} after {self.max_retries} retries"
        except BaseException as e:
            logger.info(f"Failed to get {url_path}. Reason {e}, Returning None")
            return None, f"request failed: {type(e).__name__}: {e}"[:200]

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
