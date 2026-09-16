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


class SitemapSaveResult(list):
    """The list save_sitemaps() has always returned (every scraped entry, new or
    already in the DB, each with its sitemap_id populated) -- len(), iteration, and
    indexing all work exactly as before for every existing caller. SYS-07: this
    additionally remembers how many entries were newly inserted, so
    crawl_log.article_count for task='sitemap' can reflect real new-row counts
    instead of "entries listed" without changing what the list itself contains.
    """

    def __init__(self, items, new_count: int = 0):
        super().__init__(items)
        self.new_count = new_count