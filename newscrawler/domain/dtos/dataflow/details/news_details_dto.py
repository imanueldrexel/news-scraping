from typing import List, Any, Dict, Optional
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsDetailsDTO:
    sitemap_id: int
    extracted_text: List[str]
    reporter: Optional[List[str]]
    meta_data: Optional[Dict[str, Any]]
    # SYS-37: the probe's topic for the article (filter_rubric.TOPICS_NEWS) and
    # its confidence among the news classes; None when the row predates the probe.
    topic: Optional[str] = None
    topic_confidence: Optional[float] = None
