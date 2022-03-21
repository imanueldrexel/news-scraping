from abc import abstractmethod

from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)


class DataFlowRepository:
    @abstractmethod
    def save_news_data(self, news_information) -> NewsInformationModel:
        raise NotImplementedError
