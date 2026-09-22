from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Index,
    String,
    BigInteger,
    Integer,
    SmallInteger,
    TIMESTAMP,
    JSON,
    ForeignKey,
    UniqueConstraint,
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
    crawl_status = Column(String, nullable=False, default='pending')
    # SYS-09: how many runs in a row produced no NewsDetailsDTO for this sitemap
    # (fetch failure, or any exception in _get_news_details) -- load_all_sitemaps
    # excludes it once this reaches SITEMAP_MAX_FETCH_FAILURES.
    fetch_failures = Column(Integer, nullable=False, default=0)
    last_fetch_error = Column(String, nullable=True)
    # DBT-11 (#46): added by scripts/migrate_phase3.sql for the newsletter's
    # clustering, never written by newsletter_generator.py (it keeps clusters
    # in the digest JSON). Mirrored here so the ORM matches the schema;
    # SYS-40 (#126) decides whether it is written or dropped.
    cluster_id = Column(Integer, nullable=True)

    def __init__(self, sitemap: NewsSitemapModel):
        self.headline = sitemap.headline
        self.link = sitemap.link
        self.sources = sitemap.sources
        self.category = sitemap.category
        self.posted_at = int(sitemap.posted_at.strftime("%Y%m%d")) if sitemap.posted_at else None
        self.keywords = sitemap.keywords


# Create an index on sitemap_id
Index("idx_sitemap_id", SitemapTable.sitemap_id.desc())
# SYS-29: one sitemaps row per link -- matches scripts/migrate_sitemaps_unique_link.sql's
# sitemaps_link_uq index. save_sitemaps dedups on the same key in Python; this is
# the constraint that makes that map a fast path rather than the only guard.
Index("sitemaps_link_uq", SitemapTable.link, unique=True)


class NewsArticlesTable(Base):
    __tablename__ = "articles"

    articles_id = Column(BigInteger, primary_key=True, autoincrement=True)
    sitemap_id = Column(
        BigInteger,   # DBT-11: matches the DB (bigint) and its target column
        ForeignKey(f"{SitemapTable.__tablename__}.{SitemapTable.sitemap_id.name}"),
        unique=True,
    )
    extracted_text = Column(String, nullable=False)
    meta_data = Column(JSON)
    writer = Column(JSON)
    is_embedded = Column(Boolean, nullable=False, default=False)
    knowledge_extracted    = Column(Integer, nullable=False, default=0)
    knowledge_extracted_at = Column(TIMESTAMP, nullable=True)
    knowledge_extract_attempts = Column(Integer, nullable=False, default=0)
    last_extract_error         = Column(String, nullable=True)
    # SYS-37 (#121): scripts/migrate_articles_topic.sql -- the probe's topic
    # (filter_rubric.TOPICS_NEWS) and its confidence among the news classes.
    topic                      = Column(String, nullable=True)
    topic_confidence           = Column(Float, nullable=True)

    def __init__(self, sitemap: NewsDetailsModel):
        self.sitemap_id = sitemap.sitemap_id
        # SYS-18: join paragraphs into prose -- see the matching comment in
        # sql_alchemy_articles_data_source.py's save_newsdetails (the actual write
        # path); this constructor is kept consistent even though it is presently
        # only exercised by tests, not the pg_insert(...).values(...) call.
        self.extracted_text = "\n\n".join(
            p.strip() for p in (sitemap.extracted_text or []) if p and p.strip()
        )
        self.writer = sitemap.reporter
        self.meta_data = sitemap.meta_data
        self.is_embedded = sitemap.is_embedded
        self.knowledge_extracted = 0
        self.knowledge_extracted_at = None
        self.topic = getattr(sitemap, "topic", None)
        self.topic_confidence = getattr(sitemap, "topic_confidence", None)


class ChunksTable(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # DBT-09: one row per (sitemap_id, chunk_level, chunk_index) -- matches
        # scripts/migrate_chunks_unique.sql's chunks_sitemap_level_index_uq index.
        UniqueConstraint("sitemap_id", "chunk_level", "chunk_index", name="chunks_sitemap_level_index_uq"),
    )

    chunk_id       = Column(BigInteger, primary_key=True, autoincrement=True)
    sitemap_id     = Column(BigInteger, ForeignKey(f"{SitemapTable.__tablename__}.{SitemapTable.sitemap_id.name}"), nullable=False)
    # DBT-11 (#46): in the DB since migrate_phase1.sql, absent from the ORM and
    # 100% NULL until 2026-09-22. Chunks are saved BEFORE the articles row
    # exists (save_chunk_data, then save_newsdetails_data), so the insert
    # cannot carry it; SQLAlchemyArticleDataSource.save_newsdetails links it
    # right after the article commits, and migrate_chunks_article_id.sql
    # backfilled the existing rows.
    article_id     = Column(BigInteger, ForeignKey("articles.articles_id"), nullable=True)
    chunk_level    = Column(SmallInteger, nullable=False)   # DBT-11: SMALLINT in the DB
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


# ── DBT-11 (#46): read-only ORM mirrors of the two raw-SQL tables ────────────
# crawl_log (scripts/migrate_phase5.sql) and newsletter_digests
# (scripts/migrate_phase3.sql) are written with text() SQL, never through the
# ORM. They are declared here so the schema-vs-model reflection test
# (tests/integration/test_schema_matches_orm.py) covers every table the
# pipeline owns; the hand-sync rule in CLAUDE.md has a list to sync against.
class CrawlLogTable(Base):
    __tablename__ = "crawl_log"

    log_id        = Column(BigInteger, primary_key=True, autoincrement=True)
    website       = Column(String, nullable=False)
    task          = Column(String, nullable=False)
    status        = Column(String, nullable=False)
    article_count = Column(Integer, nullable=True)
    error_msg     = Column(String, nullable=True)
    started_at    = Column(TIMESTAMP, nullable=False)
    finished_at   = Column(TIMESTAMP, nullable=True)


class NewsletterDigestsTable(Base):
    __tablename__ = "newsletter_digests"

    digest_id     = Column(BigInteger, primary_key=True, autoincrement=True)
    digest_date   = Column(Date, nullable=False, unique=True)
    file_path     = Column(String, nullable=False)
    cluster_count = Column(Integer, nullable=False, default=0)
    article_count = Column(Integer, nullable=False, default=0)
    categories    = Column(JSON, nullable=True)
    source_ids    = Column(JSON, nullable=True)
    generated_at  = Column(TIMESTAMP, nullable=False)
    generation_ms = Column(Integer, nullable=True)


# Columns the database owns and the ORM deliberately does not declare, and
# tables that are tooling rather than schema. The reflection test allows
# exactly these; anything else present in one side only is drift.
DB_OWNED_COLUMNS = {
    ("chunks", "fts_vector"),   # GENERATED ALWAYS AS to_tsvector(...) STORED, migrate_phase1.sql
}
TOOLING_TABLES = {"schema_migrations"}   # scripts/migrate.py's own ledger
