from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Boolean,
    Column,
    Index,
    String,
    BigInteger,
    Integer,
    TIMESTAMP,
    JSON,
    ForeignKey,
)
from datetime import datetime

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel

Base = declarative_base()


class SitemapTable(Base):
    __tablename__ = "sitemaps"

    sitemap_id = Column(BigInteger, primary_key=True, autoincrement=True)
    headline = Column(String)
    link = Column(String)
    sources = Column(String)
    category = Column(String, nullable=True)
    posted_at = Column(Integer)  # Changed from TIMESTAMP to BigInteger
    keywords = Column(JSON, nullable=True)
    last_crawl_attempt = Column(TIMESTAMP, nullable=True)

    def __init__(self, sitemap: NewsSitemapModel):
        self.headline = sitemap.headline
        self.link = sitemap.link
        self.sources = sitemap.sources
        self.category = sitemap.category
        self.posted_at = int(sitemap.posted_at.strftime("%Y%m%d")) if sitemap.posted_at else None
        self.keywords = sitemap.keywords


# Create an index on sitemap_id
Index("idx_sitemap_id", SitemapTable.sitemap_id.desc())


class NewsArticlesTable(Base):
    __tablename__ = "articles"

    articles_id = Column(BigInteger, primary_key=True, autoincrement=True)
    sitemap_id = Column(
        Integer,
        ForeignKey(f"{SitemapTable.__tablename__}.{SitemapTable.sitemap_id.name}"),
    )
    extracted_text = Column(String, nullable=False)
    meta_data = Column(JSON)
    writer = Column(JSON)
    is_embedded = Column(Boolean, nullable=False, default=False)
    knowledge_extracted    = Column(Integer, nullable=False, default=0)
    knowledge_extracted_at = Column(TIMESTAMP, nullable=True)

    def __init__(self, sitemap: NewsDetailsModel):
        self.sitemap_id = sitemap.sitemap_id
        self.extracted_text = sitemap.extracted_text
        self.writer = sitemap.reporter
        self.meta_data = sitemap.meta_data
        self.is_embedded = sitemap.is_embedded
        self.knowledge_extracted = 0
        self.knowledge_extracted_at = None


class ChunksTable(Base):
    __tablename__ = "chunks"

    chunk_id       = Column(BigInteger, primary_key=True, autoincrement=True)
    sitemap_id     = Column(BigInteger, ForeignKey(f"{SitemapTable.__tablename__}.{SitemapTable.sitemap_id.name}"), nullable=False)
    chunk_level    = Column(Integer, nullable=False)
    chunk_index    = Column(Integer, nullable=False, default=0)
    chunk_total    = Column(Integer, nullable=False, default=1)
    is_first_chunk = Column(Boolean, nullable=False, default=False)
    is_last_chunk  = Column(Boolean, nullable=False, default=False)
    text_content   = Column(String, nullable=False)
    token_count    = Column(Integer)
    embedding_id   = Column(String)
    chunk_status   = Column(String, nullable=False, default='pending_embedding')
    created_at     = Column(TIMESTAMP, default=datetime.utcnow)

    def __init__(self, chunk: ChunkModel):
        self.sitemap_id     = chunk.sitemap_id
        self.chunk_level    = chunk.chunk_level
        self.chunk_index    = chunk.chunk_index
        self.chunk_total    = chunk.chunk_total
        self.is_first_chunk = bool(chunk.is_first_chunk)
        self.is_last_chunk  = bool(chunk.is_last_chunk)
        self.text_content   = chunk.text_content
        self.token_count    = chunk.token_count
        self.embedding_id   = chunk.embedding_id
        self.chunk_status   = chunk.chunk_status
        self.created_at     = datetime.utcnow()


Index("idx_chunks_sitemap_id", ChunksTable.sitemap_id)
Index("idx_chunks_level", ChunksTable.chunk_level)
Index("idx_chunks_status", ChunksTable.chunk_status)


# class SourceDictionary(Base):
#     source_id = Column(BigInteger, primary_key=True)
#     source_name = Column(String)
#
#     def __init__(self, source_name: str):
#         self.source_name = source_name
#
#
# class LastCrawlingTime(Base):
#     last_crawling_time_id = Column(BigInteger, primary_key=True)
#     source_id = Column(Integer, ForeignKey(f"{SourceDictionary.__tablename__}.{SourceDictionary.source_id.name}"))
#     latest_crawled_time = Column(TIMESTAMP)
#
#     def __init__(self, source_id: int, latest_crawled_time: date):
#         self.source_id = source_id
#         self.latest_crawled_time = latest_crawled_time
