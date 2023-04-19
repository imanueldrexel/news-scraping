from datetime import datetime
from typing import List, Union

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsSitemapModel:
    headline: str
    link: str
    sources: str
    category: str = None
    timestamp: datetime = None
    keywords: Union[None, List[str]] = None

    def to_dict(self):
        doc_dict = dict()

        doc_dict["headline"] = self.headline
        doc_dict["link"] = self.link
        doc_dict["sources"] = self.sources
        doc_dict["category"] = self.category
        doc_dict["timestamp"] = self.timestamp
        doc_dict["keywords"] = self.keywords

        return doc_dict
