from datetime import datetime
from typing import List, Union, Any, Dict

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class NewsDetailsModel:
    sitemap_id: int
    extracted_text: List[str]
    reporter: List[str] = None
    meta_data: Dict[str, Any] = None

    def to_dict(self):
        doc_dict = dict()

        doc_dict["sitemap_id"] = self.sitemap_id
        doc_dict["extracted_text"] = self.extracted_text
        doc_dict["reporter"] = self.reporter
        doc_dict["meta_data"] = self.meta_data

        return doc_dict
