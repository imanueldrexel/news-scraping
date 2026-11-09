-- Phase 1 migration: chunks table
-- Run once against the newsaggregator database after sitemaps/articles tables exist.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_phase1.sql

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        BIGSERIAL PRIMARY KEY,
    sitemap_id      BIGINT NOT NULL REFERENCES sitemaps(sitemap_id),
    article_id      BIGINT NOT NULL REFERENCES articles(articles_id),
    chunk_level     SMALLINT NOT NULL CHECK (chunk_level IN (1, 2)),
    chunk_index     INT NOT NULL DEFAULT 0,
    chunk_total     INT NOT NULL DEFAULT 1,
    is_first_chunk  BOOLEAN NOT NULL DEFAULT FALSE,
    is_last_chunk   BOOLEAN NOT NULL DEFAULT FALSE,
    text_content    TEXT NOT NULL,
    token_count     INT,
    embedding_id    TEXT,
    chunk_status    TEXT NOT NULL DEFAULT 'pending_embedding'
                    CHECK (chunk_status IN ('pending_embedding', 'embedded', 'failed')),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_sitemap_id ON chunks(sitemap_id);
CREATE INDEX IF NOT EXISTS idx_chunks_article_id ON chunks(article_id);
CREATE INDEX IF NOT EXISTS idx_chunks_level      ON chunks(chunk_level);
CREATE INDEX IF NOT EXISTS idx_chunks_status     ON chunks(chunk_status);

-- Full-text search column.
-- Uses 'simple' config (works on every PostgreSQL install).
-- For Indonesian stemming you would need a custom text search configuration;
-- swap 'simple' for your config name once it exists.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS fts_vector TSVECTOR
        GENERATED ALWAYS AS (to_tsvector('simple', text_content)) STORED;

CREATE INDEX IF NOT EXISTS idx_chunks_fts ON chunks USING GIN(fts_vector);
