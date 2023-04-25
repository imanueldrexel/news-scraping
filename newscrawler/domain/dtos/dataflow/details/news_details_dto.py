from typing import List, Any, Dict
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsDetailsDTO:
    sitemap_id: int
    extracted_text: List[str]
    reporter: List[str]
    meta_data: Dict[str, Any]