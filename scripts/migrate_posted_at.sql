-- Fix sitemaps.posted_at column type: TIMESTAMP → INTEGER (YYYYMMDD)
-- Run once against newsaggregator after the database was created with init.sql.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_posted_at.sql

ALTER TABLE sitemaps
    ALTER COLUMN posted_at TYPE INTEGER
    USING TO_CHAR(posted_at, 'YYYYMMDD')::INTEGER;
