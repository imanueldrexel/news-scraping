from typing import List, Union
from datetime import datetime
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SitemapDTO:
    headline: str
    link: str
    sources: str
    category: str = None
    timestamp: datetime = None
    keywords: Union[None, List[str]] = None
