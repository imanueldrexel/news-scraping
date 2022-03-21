from abc import abstractmethod
from typing import Union

from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)


class CrawlerService:
    @abstractmethod
    def crawl_url(self, website_name: str) -> NewsInformationDTO:
        raise NotImplementedError

    @abstractmethod
    def save_scraped_data(self, scraped_data) -> Union[None, NewsInformationModel]:
        raise NotImplementedError
