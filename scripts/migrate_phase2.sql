-- Phase 2: Knowledge Extraction — Schema Migration
-- Run once against the newsaggregator database.

-- ─────────────────────────────────────────────────
-- ENTITIES TABLE
-- ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    entity_id       BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('PERSON', 'ORGANIZATION', 'LOCATION')),
    subtype         TEXT,
    ticker          TEXT,
    first_seen_at   DATE,
    last_seen_at    DATE,
    mention_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (normalized_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_type       ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_ticker     ON entities(ticker);
CREATE INDEX IF NOT EXISTS idx_entities_normalized ON entities(normalized_name);

-- ─────────────────────────────────────────────────
-- ENTITY_ALIASES TABLE
-- Maps known name variants to a canonical entity_id.
-- ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_id         BIGSERIAL PRIMARY KEY,
    alias_name       TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    entity_id        BIGINT NOT NULL REFERENCES entities(entity_id),
    UNIQUE (normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_aliases_entity_id ON entity_aliases(entity_id);

-- ─────────────────────────────────────────────────
-- ENTITY_MENTIONS TABLE
-- ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id      BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(entity_id),
    sitemap_id      BIGINT NOT NULL REFERENCES sitemaps(sitemap_id),
    article_id      BIGINT NOT NULL REFERENCES articles(articles_id),
    chunk_id        BIGINT REFERENCES chunks(chunk_id),
    context_snippet TEXT,
    event_type      TEXT,
    posted_at       DATE NOT NULL,
    source          TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, sitemap_id)
);

CREATE INDEX IF NOT EXISTS idx_mentions_entity_id  ON entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_posted_at  ON entity_mentions(posted_at);
CREATE INDEX IF NOT EXISTS idx_mentions_source     ON entity_mentions(source);
CREATE INDEX IF NOT EXISTS idx_mentions_event_type ON entity_mentions(event_type);

-- ─────────────────────────────────────────────────
-- API_USAGE_LOG TABLE
-- Daily counter guard for Gemini API calls.
-- ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_usage_log (
    log_id      BIGSERIAL PRIMARY KEY,
    log_date    DATE NOT NULL,
    api_name    TEXT NOT NULL,
    call_count  INT NOT NULL DEFAULT 0,
    UNIQUE (log_date, api_name)
);

-- ─────────────────────────────────────────────────
-- ALTER articles TABLE
-- ─────────────────────────────────────────────────
ALTER TABLE articles ADD COLUMN IF NOT EXISTS knowledge_extracted    INT NOT NULL DEFAULT 0;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS knowledge_extracted_at TIMESTAMP;
