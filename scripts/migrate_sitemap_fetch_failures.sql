-- SYS-09: track fetch/extraction failures separately from "not yet attempted".
--
-- A sitemap whose article URL is permanently 404/403/timeout, or whose fetch
-- raises, was never stamped last_crawl_attempt (only successfully-extracted
-- sitemaps are -- see crawler_service_impl.py's mark_sitemaps_attempted call),
-- so it stayed at the top of the "no article yet" queue (ordered posted_at DESC)
-- and consumed one of load_all_sitemaps' LIMIT slots on every single run,
-- forever. fetch_failures lets load_all_sitemaps exclude a sitemap once it has
-- failed enough times in a row, without touching the cooldown/retry behaviour
-- for a sitemap that has never been attempted or that failed only once or twice
-- (still probably transient).
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_sitemap_fetch_failures.sql

ALTER TABLE sitemaps ADD COLUMN IF NOT EXISTS fetch_failures INT NOT NULL DEFAULT 0;
ALTER TABLE sitemaps ADD COLUMN IF NOT EXISTS last_fetch_error TEXT;

-- Partial index: only the (small) set of sitemaps that have ever failed need to
-- be found quickly; everything else stays at the default 0 and never needs it.
CREATE INDEX IF NOT EXISTS idx_sitemaps_fetch_failures ON sitemaps(fetch_failures) WHERE fetch_failures > 0;
