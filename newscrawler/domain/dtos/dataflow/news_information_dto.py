from typing import List

from pydantic.dataclasses import dataclass


from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO


@dataclass(frozen=True)
class NewsInformationDTO:
    scraped_news: List[SitemapDTO]
