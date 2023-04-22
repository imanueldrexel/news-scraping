import logging
from typing import List

from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.services.crawler_service import CrawlerService

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CrawlerAPI:
    def __init__(self, crawler_service: CrawlerService):
        self.crawler_service = crawler_service

    def crawl_website(self, website_name: str):
        self.crawler_service.crawl_sitemaps(website_name)

    def crawl_website_in_batch(self, website_names: List[str]):
        for idx, website_name in enumerate(website_names):
            self.crawl_website(website_name)

    def craw_full_text(self, sitemap_ids: List[int]):
        self.crawler_service.crawl_newsdetails(sitemap_ids)
