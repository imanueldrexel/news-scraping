-- Migration: add is_embedded, knowledge_extracted, knowledge_extracted_at to articles table.
-- Run once against the newsaggregator database.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_articles_columns.sql

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS is_embedded              INTEGER   NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS knowledge_extracted      INTEGER   NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS knowledge_extracted_at   TIMESTAMP NULL;

-- Make chunks.article_id nullable (new pipeline creates chunks before articles exist).
ALTER TABLE chunks ALTER COLUMN article_id DROP NOT NULL;

-- Convert articles.is_embedded from INTEGER to BOOLEAN.
ALTER TABLE articles ALTER COLUMN is_embedded DROP DEFAULT;
ALTER TABLE articles ALTER COLUMN is_embedded TYPE BOOLEAN USING is_embedded::boolean;
ALTER TABLE articles ALTER COLUMN is_embedded SET DEFAULT FALSE;
