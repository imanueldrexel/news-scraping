from dataclasses import dataclass
from typing import Optional


@dataclass
class ChunkModel:
    sitemap_id: int
    chunk_level: int
    chunk_index: int
    chunk_total: int
    is_first_chunk: bool
    is_last_chunk: bool
    text_content: str
    token_count: int
    embedding_id: Optional[str] = None
    chunk_status: str = 'pending_embedding'
    chunk_id: Optional[int] = None
