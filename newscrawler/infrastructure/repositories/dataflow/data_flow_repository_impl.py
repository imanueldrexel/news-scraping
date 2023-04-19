from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)


class DataFlowRepositoryImpl(DataFlowRepository):
    def __init__(self, write_news_data_source: NewsDataSource):
        self.write_news_data_source = write_news_data_source

    # def load_latest_scrapped_time(self):
    #     self.

    def save_news_data(
        self, news_information: NewsInformationDTO
    ) -> NewsInformationModel:
        news_information_model = self.to_news_information_model(news_information)
        self.write_news_data_source.save(news_information_model.news)
        return news_information_model

    def to_news_information_model(
        self, news_information: NewsInformationDTO
    ) -> NewsInformationModel:
        news_models = [
            self._to_news_data_model(news) for news in news_information.scraped_news
        ]

        return NewsInformationModel(news=news_models)

    @staticmethod
    def _to_news_data_model(
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
