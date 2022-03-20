from typing import List

from pydantic.dataclasses import dataclass


from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO


@dataclass(frozen=True)
class NewsInformationDTO:
    scraped_news: List[NewsDetailsDTO]
