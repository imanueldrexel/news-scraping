from datetime import datetime

from sqlalchemy import Column, BigInteger, Integer, String, Date, TIMESTAMP, ForeignKey, Index

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import Base
from newscrawler.infrastructure.datasource.dataflow.model.entity_model import (
    EntityModel,
    EntityMentionModel,
)


class EntitiesTable(Base):
    __tablename__ = "entities"

    entity_id       = Column(BigInteger, primary_key=True, autoincrement=True)
    name            = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    entity_type     = Column(String, nullable=False)
    subtype         = Column(String, nullable=True)
    ticker          = Column(String, nullable=True)
    first_seen_at   = Column(Date, nullable=True)
    last_seen_at    = Column(Date, nullable=True)
    mention_count   = Column(Integer, nullable=False, default=0)
    created_at      = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at      = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, model: EntityModel):
        self.name            = model.name
        self.normalized_name = model.normalized_name
        self.entity_type     = model.entity_type
        self.subtype         = model.subtype
        self.ticker          = model.ticker
        self.first_seen_at   = model.first_seen_at
        self.last_seen_at    = model.last_seen_at
        self.mention_count   = model.mention_count
        self.created_at      = datetime.utcnow()
        self.updated_at      = datetime.utcnow()


Index("idx_entities_type",       EntitiesTable.entity_type)
Index("idx_entities_ticker",     EntitiesTable.ticker)
Index("idx_entities_normalized", EntitiesTable.normalized_name)


class EntityAliasesTable(Base):
    __tablename__ = "entity_aliases"

    alias_id         = Column(BigInteger, primary_key=True, autoincrement=True)
    alias_name       = Column(String, nullable=False)
    normalized_alias = Column(String, nullable=False, unique=True)
    entity_id        = Column(BigInteger, ForeignKey("entities.entity_id"), nullable=False)


Index("idx_aliases_entity_id", EntityAliasesTable.entity_id)


class EntityMentionsTable(Base):
    __tablename__ = "entity_mentions"

    mention_id      = Column(BigInteger, primary_key=True, autoincrement=True)
    entity_id       = Column(BigInteger, ForeignKey("entities.entity_id"), nullable=False)
    sitemap_id      = Column(BigInteger, ForeignKey("sitemaps.sitemap_id"), nullable=False)
    article_id      = Column(BigInteger, ForeignKey("articles.articles_id"), nullable=False)
    chunk_id        = Column(BigInteger, ForeignKey("chunks.chunk_id"), nullable=True)
    context_snippet = Column(String, nullable=True)
    event_type      = Column(String, nullable=True)
    posted_at       = Column(Date, nullable=False)
    source          = Column(String, nullable=False)
    created_at      = Column(TIMESTAMP, default=datetime.utcnow)

    def __init__(self, model: EntityMentionModel):
        self.entity_id       = model.entity_id
        self.sitemap_id      = model.sitemap_id
        self.article_id      = model.article_id
        self.chunk_id        = model.chunk_id
        self.context_snippet = model.context_snippet
        self.event_type      = model.event_type
        self.posted_at       = model.posted_at
        self.source          = model.source
        self.created_at      = datetime.utcnow()


Index("idx_mentions_entity_id",  EntityMentionsTable.entity_id)
Index("idx_mentions_posted_at",  EntityMentionsTable.posted_at)
Index("idx_mentions_source",     EntityMentionsTable.source)
Index("idx_mentions_event_type", EntityMentionsTable.event_type)


class ApiUsageLogTable(Base):
    __tablename__ = "api_usage_log"

    log_id     = Column(BigInteger, primary_key=True, autoincrement=True)
    log_date   = Column(Date, nullable=False)
    api_name   = Column(String, nullable=False)
    call_count = Column(Integer, nullable=False, default=0)
