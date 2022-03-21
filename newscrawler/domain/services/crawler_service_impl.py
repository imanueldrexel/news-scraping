from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.domain.services.crawler_service import CrawlerService
from typing import Dict, Union


class CrawlerServiceImpl(CrawlerService):
    def __init__(
        self,
        web_url_dict: Dict[WebsiteName, str],
        crawler_dict: Dict[WebsiteName, Crawler],
        data_flow_repo: DataFlowRepository,
    ):
        self.web_url_dict = web_url_dict
        self.crawler_dict = crawler_dict
        self.data_flow_repo = data_flow_repo

    def crawl_url(self, website_name: WebsiteName) -> NewsInformationDTO:
        web_url = self.web_url_dict[website_name]
        web_crawler = self.crawler_dict[website_name]
        crawled_data = web_crawler.get_news_data(web_url)

        return crawled_data

    def save_scraped_data(self, scraped_data) -> Union[None, NewsInformationModel]:
        final_result = None
        if isinstance(scraped_data, NewsInformationDTO):
            final_result = self.data_flow_repo.save_news_data(scraped_data)

        return final_result
