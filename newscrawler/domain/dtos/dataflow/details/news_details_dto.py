from typing import List, Dict, Union
from datetime import date
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsDetailsDTO:
    headline: str
    link: str
    sources: str
    extracted_text: List[str]
    category: str = None
    timestamp: date = None
    keywords: Union[None, List[str]] = None
