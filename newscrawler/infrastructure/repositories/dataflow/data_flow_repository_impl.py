from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsDataModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)
from extractivenewssummarizer import nlp


class DataFlowRepositoryImpl(DataFlowRepository):
    def __init__(self, write_news_data_source: NewsDataSource):
        self.write_news_data_source = write_news_data_source

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
        news_details: NewsDetailsDTO,
    ) -> NewsDataModel:
        return NewsDataModel(
            headline=news_details.headline,
            extracted_text=news_details.extracted_text,
            link=news_details.link,
            sources=news_details.sources,
            category=news_details.category,
            timestamp=news_details.timestamp,
            keywords=news_details.keywords,
        )
