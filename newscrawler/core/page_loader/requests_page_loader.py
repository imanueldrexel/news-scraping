import logging
import requests

from bs4 import BeautifulSoup

from newscrawler.core.constants import REQUEST_MAX_RETRIES
from newscrawler.core.page_loader.page_loader import PageLoader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RequestsPageLoader(PageLoader):
    def __init__(self):
        self.max_retries = REQUEST_MAX_RETRIES

    def get_soup(self, url_path: str):
        headers = {
            "Accept-Encoding": "gzip, deflate, sdch",
            "Accept-Language": "en-US,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 "
            "Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }
        try:
            response = requests.get(url_path, headers=headers, timeout=(10, 27))
            soup = BeautifulSoup(response.content, "html.parser")
            counter = 0
            while soup is None and counter < self.max_retries:
                logger.info("Retrying to connect")
                response = requests.get(url_path, headers=headers, timeout=(10, 27))
                soup = BeautifulSoup(response.content, "html.parser")
            return soup
        except requests.exceptions.ReadTimeout:
            for idx in range(self.max_retries):
                logger.info(f"Retry {idx} to connect")
                try:
                    response = requests.get(url_path, headers=headers, timeout=(10, 27))
                    soup = BeautifulSoup(response.content, "html.parser")
                    return soup
                except requests.exceptions.ReadTimeout:
                    continue

            logger.info(
                f"Failed to fetch {url_path}. Reason: ReadTimeout, Returning None"
            )
            return None
        except BaseException as e:
            logger.info(f"Failed to fetch {url_path}. Reason: {e}. Returning None")
            return None
