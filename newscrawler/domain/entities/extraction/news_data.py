from pydantic.dataclasses import dataclass
from datetime import date
from typing import List, Union

from newscrawler.domain.entities.extraction.extracted_data import ExtractedData


@dataclass(frozen=True)
class NewsData(ExtractedData):
    headline: str
    extracted_text: List[str]
    link: str
    sources: str
    category: str = None
    timestamp: date = None
    keywords: Union[None, List[str]] = None

    def to_dict(self):
        doc_dict = dict()

        doc_dict["headline"] = self.headline
        doc_dict["extracted_text"] = self.extracted_text
        doc_dict["link"] = self.link
        doc_dict["sources"] = self.sources
        doc_dict["category"] = self.category
        doc_dict["timestamp"] = self.timestamp
        doc_dict["keywords"] = self.keywords

        return doc_dict
