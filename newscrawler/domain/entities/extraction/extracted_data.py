from pydantic.dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ExtractedData:
    headline: str
    extracted_text: List[str]
