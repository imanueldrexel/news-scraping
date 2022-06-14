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
                        url_path, headers=self.headers, timeout=(10, 27)
                    )
                    return response
                except requests.exceptions.ReadTimeout or requests.exceptions.ConnectionError:
                    continue
            return None
        except BaseException as e:
            logger.info(f"Failed to get {url_path}. Reason {e}, Returning None")
            return None

    def get_soup(self, url_path: str):
        response = self.get_url(url_path)
        if response and response.status_code == 200:
            try:
                soup = BeautifulSoup(response.content, "html.parser")
                return soup
            except BaseException as e:
                logger.info(
                    f"Failed to get the HTML for {url_path}. Reason: {e}, Returning None"
                )
                return None
        elif response:
            logger.info(
                f"Failed to get {url_path}. Status Code: {response.status_code}, Returning None"
            )
            return None
