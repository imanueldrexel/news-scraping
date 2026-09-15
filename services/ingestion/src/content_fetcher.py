"""Content fetcher for downloading article HTML."""

import logging
import requests
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of fetching a URL."""

    url: str
    html: Optional[str]
    success: bool
    error: Optional[str] = None


class ContentFetcher:
    """
    Fetches HTML content from URLs.
    Handles retries, timeouts, and parallel fetching.
    """

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5,id;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Cache-Control": "max-age=0",
    }

    def __init__(
        self,
        timeout: Tuple[int, int] = (10, 30),
        max_retries: int = 3,
        max_workers: int = 10,
    ):
        """
        Initialize content fetcher.

        Args:
            timeout: (connect_timeout, read_timeout) in seconds
            max_retries: Maximum retry attempts
            max_workers: Maximum parallel fetch workers
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        session.headers.update(self.DEFAULT_HEADERS)

        # Configure retries
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def fetch(self, url: str) -> FetchResult:
        """
        Fetch HTML content from a URL.

        Args:
            url: URL to fetch

        Returns:
            FetchResult with HTML content or error
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # Detect encoding
            if response.encoding is None:
                response.encoding = response.apparent_encoding or "utf-8"

            return FetchResult(
                url=url,
                html=response.text,
                success=True,
            )

        except requests.Timeout as e:
            logger.warning(f"Timeout fetching {url}: {e}")
            return FetchResult(
                url=url,
                html=None,
                success=False,
                error=f"Timeout: {e}",
            )

        except requests.RequestException as e:
            logger.warning(f"Error fetching {url}: {e}")
            return FetchResult(
                url=url,
                html=None,
                success=False,
                error=str(e),
            )

    def fetch_batch(self, urls: list[str]) -> list[FetchResult]:
        """
        Fetch multiple URLs in parallel.

        Args:
            urls: List of URLs to fetch

        Returns:
            List of FetchResult objects
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self.fetch, url): url for url in urls}

            for future in as_completed(future_to_url):
                result = future.result()
                results.append(result)

        return results

    def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch URL and return BeautifulSoup object.

        Args:
            url: URL to fetch

        Returns:
            BeautifulSoup object or None on failure
        """
        result = self.fetch(url)
        if result.success and result.html:
            return BeautifulSoup(result.html, "html.parser")
        return None

    def close(self):
        """Close the session."""
        self.session.close()
