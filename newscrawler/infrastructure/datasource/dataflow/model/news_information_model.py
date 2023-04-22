from typing import List, Union
from pydantic.dataclasses import dataclass

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel


@dataclass(frozen=True)
class NewsInformationModel:
    news: List[Union[NewsSitemapModel, NewsDetailsModel]]
