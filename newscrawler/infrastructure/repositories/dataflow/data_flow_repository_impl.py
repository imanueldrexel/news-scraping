from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import DataFlowRepository
from newscrawler.infrastructure.datasource.dataflow.model.data_flow_mapper import DataFlowMapper
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource


class DataFlowRepositoryImpl(DataFlowRepository):
    def __init__(
        self,
        write_news_data_source: NewsDataSource
    ):
        self.write_news_data_source = write_news_data_source

    def save_news_data(self, news_information):
        news_information_model = DataFlowMapper.to_news_information_model(
            news_information
        )
        self.write_news_data_source.save(news_information_model.news)
        return news_information_model
