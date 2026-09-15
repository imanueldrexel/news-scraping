from abc import abstractmethod
from typing import Union, List

from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)


class CrawlerService:
    @abstractmethod
    def crawl_sitemaps(self, website_name: str) -> List[NewsInformationDTO]:
        raise NotImplementedError

    @abstractmethod
    def crawl_newsdetails(self, website_name: str, specific_sitemaps: List[NewsInformationDTO] = None):
        raise NotImplementedError

    @abstractmethod
    def save_scraped_data(self, scraped_data) -> Union[None, NewsInformationModel]:
        raise NotImplementedError

    @abstractmethod
    def save_embedding_data(self, scraped_data) -> Union[None, NewsInformationModel]:
        raise NotImplementedError