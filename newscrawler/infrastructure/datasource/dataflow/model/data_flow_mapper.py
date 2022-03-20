from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsDataModel
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import NewsInformationModel


class DataFlowMapper:
    @staticmethod
    def to_news_information_model(
            news_information: NewsInformationDTO,
    ) -> NewsInformationModel:
        news_models = [
            DataFlowMapper.to_news_data_model(news)
            for news in news_information.scraped_news
        ]

        return NewsInformationModel(news=news_models)

    @staticmethod
    def to_news_data_model(
            news_details: NewsDetailsDTO,
    ) -> NewsDataModel:
        return NewsDataModel(
            headline=news_details.headline,
            extracted_text=news_details.extracted_text,
            link=news_details.link,
            sources=news_details.sources,
            category=news_details.category,
            timestamp=news_details.timestamp,
            keywords=news_details.keywords
        )
