from typing import List, Union, Optional
from datetime import datetime
from pydantic import field_validator
from pydantic.dataclasses import dataclass


def posted_at_datetime(value):
    """sitemaps.posted_at as a datetime: the stored int yyyymmdd (SYS-11) is
    midnight of that day; a datetime (or anything else) passes through, None stays
    None. SYS-90 (#255): pydantic 2 reads an int given to a `datetime` field as
    Unix seconds, so 20260918 became 1970-08-23 and 193 articles were saved with
    posted_at 19700823 by a script that built DTOs from stored rows."""
    if isinstance(value, int) and not isinstance(value, bool) and 10000101 <= value <= 99991231:
        return datetime.strptime(str(value), "%Y%m%d")
    return value


@dataclass(frozen=True)
class SitemapDTO:
    headline: str
    link: str
    sources: str
    category: Optional[str] = None
    timestamp: Optional[datetime] = None     # DBT-01: pydantic 2 rejects an explicit None for `datetime`
    keywords: Union[None, List[str]] = None
    sitemap_id: Optional[int] = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _stored_date(cls, value):
        """A stored row's int yyyymmdd is a date, never Unix seconds (SYS-90)."""
        return posted_at_datetime(value)
