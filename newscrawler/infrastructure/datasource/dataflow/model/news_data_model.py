from datetime import datetime
from typing import List, Optional, Union

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsSitemapModel:
    headline: str
    link: str
    sources: str
    category: Optional[str] = None
    posted_at: datetime = None
    keywords: Union[None, List[str]] = None
    sitemap_id: Optional[int] = None

    def to_dict(self):
        doc_dict = dict()

        doc_dict["headline"] = self.headline
        doc_dict["link"] = self.link
        doc_dict["sources"] = self.sources
        doc_dict["category"] = self.category
        doc_dict["posted_at"] = self.posted_at
        doc_dict["keywords"] = self.keywords
        doc_dict["sitemap_id"] = self.sitemap_id

        return doc_dict