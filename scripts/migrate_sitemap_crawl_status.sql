-- SYS-16: add a terminal-state marker to sitemaps.
--
-- last_crawl_attempt alone can't distinguish a permanent rejection (article is
-- off-topic) from a transient one (extractor returned nothing usable this time) --
-- both look identical to load_all_sitemaps' "no articles row, cooldown elapsed"
-- queue, so a semantically-rejected sitemap gets re-fetched, re-run through the
-- extractor and the filter, rejected again for the same deterministic reason, and
-- re-queued forever. 73,364 of 99,737 rows (73%) were in this state on 2026-09-16.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_sitemap_crawl_status.sql

ALTER TABLE sitemaps ADD COLUMN IF NOT EXISTS crawl_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE sitemaps DROP CONSTRAINT IF EXISTS sitemaps_crawl_status_check;
ALTER TABLE sitemaps ADD CONSTRAINT sitemaps_crawl_status_check
    CHECK (crawl_status IN ('pending', 'rejected_filter', 'empty_extraction', 'saved'));

CREATE INDEX IF NOT EXISTS idx_sitemaps_crawl_status ON sitemaps(crawl_status);

-- Backfill existing rows that already have an articles row as 'saved', so the
-- column is consistent with reality without waiting for a re-crawl. Everything
-- else keeps the 'pending' default; run scripts/backfill_sitemap_crawl_status.py
-- afterward to classify the 73k attempted-no-article rows into rejected_filter /
-- empty_extraction using the semantic filter against their stored headline.
UPDATE sitemaps s
SET crawl_status = 'saved'
WHERE crawl_status = 'pending'
  AND EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = s.sitemap_id);
