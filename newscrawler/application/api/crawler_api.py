import logging
from typing import List


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CrawlerAPI:
    def __init__(self, crawler_service):
        self.crawler_service = crawler_service

    def crawl_website(self, website_name: str):
        return self.crawler_service.crawl_url(website_name)

    def crawl_website_in_batch(self, website_names: List[str]):
        for idx, website_name in enumerate(website_names):
            result = self.crawl_website(website_name)
