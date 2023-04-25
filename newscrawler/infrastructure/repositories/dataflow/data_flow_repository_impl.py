from typing import List, Dict, Tuple, Union

from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)


class DataFlowRepositoryImpl(DataFlowRepository):
    def __init__(self, write_news_data_source: NewsDataSource):
        self.write_news_data_source = write_news_data_source

    def load_target_news(self, target_sitemaps_id: List[int]) -> Dict[str, List[Tuple[int, str]]]:
        return self.write_news_data_source.load_target_news(target_sitemaps_id)

    def save_sitemap_data(
            self, sitemaps: List[NewsDetailsDTO]
    ):
        news_sitemap_model = self.to_news_information_model(sitemaps)
        self.write_news_data_source.save_sitemap(news_sitemap_model)

    def save_newsdetails_data(self, newsdetails: List[NewsDetailsDTO]):
        newsdetail_model = self.to_news_information_model(newsdetails)
        self.write_news_data_source.save_newsdetails(newsdetail_model)

    def to_news_information_model(
            self, news_information: List[Union[NewsDetailsDTO, SitemapDTO]]
    ) -> List[Union[NewsSitemapModel, NewsDetailsModel]]:
        if isinstance(news_information[0], SitemapDTO):
            sitemap_model = [
                self._to_sitemap_data_model(news) for news in news_information
            ]
            return sitemap_model
        elif isinstance(news_information[0], NewsDetailsDTO):
            newsdetail_model = [
                self._to_newsdetail_data_model(news) for news in news_information
            ]
            return newsdetail_model

    @staticmethod
    def _to_sitemap_data_model(
            news_details: SitemapDTO,
    ) -> NewsSitemapModel:
        return NewsSitemapModel(
            headline=news_details.headline,
            link=news_details.link,
            sources=news_details.sources,
            category=news_details.category,
            timestamp=news_details.timestamp,
            keywords=news_details.keywords,
        )

    @staticmethod
    def _to_newsdetail_data_model(
            news_details: NewsDetailsDTO,
    ) -> NewsDetailsModel:
        return NewsDetailsModel(
            sitemap_id=news_details.sitemap_id,
            extracted_text=news_details.extracted_text,
            reporter=news_details.reporter,
            meta_data=news_details.meta_data
        )
