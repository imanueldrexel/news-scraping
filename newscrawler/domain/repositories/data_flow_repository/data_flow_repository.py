from abc import abstractmethod


class DataFlowRepository:
    @abstractmethod
    def save_news_data(self, news_information):
        raise NotImplementedError
