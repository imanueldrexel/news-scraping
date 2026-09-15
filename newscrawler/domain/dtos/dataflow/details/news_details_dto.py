from typing import List, Any, Dict, Optional
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsDetailsDTO:
    sitemap_id: int
    extracted_text: List[str]
    reporter: Optional[List[str]]
    meta_data: Optional[Dict[str, Any]]
