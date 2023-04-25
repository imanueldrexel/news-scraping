from abc import abstractmethod
from typing import List, Dict, Tuple

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)


class DataFlowRepository:
    @abstractmethod
    def save_sitemap_data(self, sitemaps: List[SitemapDTO]) -> NewsInformationModel:
        raise NotImplementedError

    @abstractmethod
    def save_newsdetails_data(self, sitemaps: List[NewsDetailsDTO]) -> NewsInformationModel:
        raise NotImplementedError

    def load_target_news(self, target_sitemaps_id: List[int]) -> Dict[str, List[Tuple[int, str]]]:
        raise NotImplementedError
