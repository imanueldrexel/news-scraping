-- Migration: add last_crawl_attempt to sitemaps (Bug B fix).
-- Lets the crawler mark a sitemap as attempted after fetch+filter so filtered-out /
-- failed sitemaps are not re-crawled until a cooldown window elapses, instead of being
-- re-selected forever by the 'sitemaps with no article' queue.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_sitemap_crawl_attempt.sql

ALTER TABLE sitemaps ADD COLUMN IF NOT EXISTS last_crawl_attempt TIMESTAMP NULL;
