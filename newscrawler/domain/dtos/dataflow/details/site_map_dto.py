from typing import List, Union, Optional
from datetime import datetime
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SitemapDTO:
    headline: str
    link: str
    sources: str
    category: Optional[str] = None
    timestamp: datetime = None
    keywords: Union[None, List[str]] = None
    sitemap_id: Optional[int] = None
