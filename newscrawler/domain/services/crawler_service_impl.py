from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.crawler_url_list import WEB_URL_DICT
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.domain.services.crawler_service import CrawlerService
from typing import List

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler


class CrawlerServiceImpl(CrawlerService):
    def __init__(
            self,
            data_flow_repo: DataFlowRepository,
    ):
        self.crawler_dict = CRAWLER_DICT
        self.web_url_dict = WEB_URL_DICT
        self.data_flow_repo = data_flow_repo

    def crawl_sitemaps(self, website_name: str):
        web_crawler: Crawler = self.crawler_dict.get(website_name)
        news = web_crawler.get_news_in_bulk()
        sitemaps = web_crawler.batch_crawling_sitemap(news, website_name)
        if sitemaps:
            self.save_scraped_data(sitemaps)

    def crawl_newsdetails(self, target_sitemaps_id: List[int]):
        target_news = self.data_flow_repo.load_target_news(target_sitemaps_id)
        for website_name, links in target_news.items():
            if website_name != "BATAMPOS":
                continue
            web_crawler: Crawler = self.crawler_dict.get(website_name)
            newsdetails = web_crawler.batch_crawling_details(links, website_name)
            if newsdetails:
                self.save_scraped_data(newsdetails)

    def save_scraped_data(self, scraped_data):
        if isinstance(scraped_data[0], SitemapDTO):
            self.data_flow_repo.save_sitemap_data(scraped_data)
        elif isinstance(scraped_data[0], NewsDetailsDTO):
            self.data_flow_repo.save_newsdetails_data(scraped_data)
