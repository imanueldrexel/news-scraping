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
        try:
            response = requests.get(
                url_path, headers=self.headers, timeout=(10, 27), stream=True
            )
            return response
        except requests.exceptions.ReadTimeout or requests.exceptions.ConnectionError:
            for idx in range(self.max_retries):
                logger.info(f"Retry {idx} to connect")
                try:
                    response = requests.get(
                        url_path, headers=self.headers, timeout=(20, 30)
                    )
                    return response
                except (
                    requests.exceptions.ReadTimeout
                    or requests.exceptions.ConnectionError
                ):
                    continue
            return None
        except BaseException as e:
            logger.info(f"Failed to get {url_path}. Reason {e}, Returning None")
            return None

    def get_soup(self, url_path: str):
        response = self.get_url(url_path)
        if response and response.status_code == 200:
            # SYS-14: a 200 that was redirected to an error/home page is a soft-404,
            # not a real article -- reject it before it reaches the extractor chain.
            final_path = urlparse(response.url).path
            if response.history and ERROR_PATH_PATTERN.search(final_path):
                logger.info(
                    f"Failed to get {url_path}. Redirected to error page {response.url}, Returning None"
                )
                return None
            try:
                soup = BeautifulSoup(response.content, "html.parser")
            except BaseException as e:
                logger.info(
                    f"Failed to get the HTML for {url_path}. Reason: {e}, Returning None"
                )
                return None

            # Some sites render the error page in place (no redirect) but still
            # mark it with a canonical link pointing at the real error/home page.
            canonical = soup.find("link", rel="canonical")
            canonical_href = canonical.get("href") if canonical else None
            if canonical_href and ERROR_PATH_PATTERN.search(urlparse(canonical_href).path):
                logger.info(
                    f"Failed to get {url_path}. Canonical points to error page {canonical_href}, Returning None"
                )
                return None

            return soup
        elif response:
            logger.info(
                f"Failed to get {url_path}. Status Code: {response.status_code}, Returning None"
            )
            return None
