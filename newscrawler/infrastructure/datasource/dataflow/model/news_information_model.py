from typing import List
from pydantic.dataclasses import dataclass

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsDataModel


@dataclass(frozen=True)
class NewsInformationModel:
    news: List[NewsDataModel]
