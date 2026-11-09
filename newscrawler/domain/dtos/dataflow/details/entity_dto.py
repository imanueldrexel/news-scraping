from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class EntityDTO:
    name: str
    entity_type: str          # 'PERSON' | 'ORGANIZATION' | 'LOCATION'
    normalized_name: str
    subtype: Optional[str] = None
    ticker: Optional[str] = None
    first_seen_at: Optional[date] = None
    last_seen_at: Optional[date] = None
    mention_count: int = 0
    entity_id: Optional[int] = None  # populated after DB upsert
