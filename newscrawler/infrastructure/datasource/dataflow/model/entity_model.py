from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class EntityModel:
    name: str
    normalized_name: str
    entity_type: str          # 'PERSON' | 'ORGANIZATION' | 'LOCATION'
    subtype: Optional[str] = None
    ticker: Optional[str] = None
    first_seen_at: Optional[date] = None
    last_seen_at: Optional[date] = None
    mention_count: int = 0
    entity_id: Optional[int] = None  # populated after DB upsert


@dataclass
class EntityMentionModel:
    entity_id: int
    sitemap_id: int
    article_id: int
    posted_at: date
    source: str
    chunk_id: Optional[int] = None
    context_snippet: Optional[str] = None
    event_type: Optional[str] = None
