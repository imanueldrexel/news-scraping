from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class EntityMentionDTO:
    entity_id: int
    sitemap_id: int
    article_id: int
    posted_at: date
    source: str
    chunk_id: Optional[int] = None
    context_snippet: Optional[str] = None
    event_type: Optional[str] = None
    mention_id: Optional[int] = None  # populated after DB insert
