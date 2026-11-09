from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ChunkDTO:
    sitemap_id: int
    chunk_level: int          # 1=article summary, 2=paragraph
    chunk_index: int          # 0-based position within level
    chunk_total: int          # total L2 chunks in this article
    is_first_chunk: bool
    is_last_chunk: bool
    text_content: str
    token_count: int
    title: str
    source: str
    category: Optional[str]
    posted_at: Optional[int]  # YYYYMMDD integer (matches SitemapTable.posted_at)
    reporter: Optional[List[str]] = field(default_factory=list)
    chunk_id: Optional[int] = None       # set after PostgreSQL insert
    embedding_id: Optional[str] = None  # set after FAISS insert (LangChain UUID)
    chunk_status: str = 'pending_embedding'
