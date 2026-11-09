-- DBT-64 (#286): entity_mentions.chunk_id references chunks(chunk_id) (migrate_phase2.sql) with
-- no index, so every DELETE FROM chunks checked the foreign key by a sequential scan of
-- entity_mentions: deleting 17,222 chunk rows took 9 minutes on 2026-10-08, and SYS-109's
-- re-chunk deletes ~370k. The repair and settle scripts also select and delete mentions by
-- sitemap_id, which the unique key (entity_id, sitemap_id) cannot serve.
--
-- Idempotent. Usage (prefer scripts/migrate.py):
--   psql -U postgres -d newsaggregator -f scripts/migrate_entity_mentions_indexes.sql

CREATE INDEX IF NOT EXISTS idx_mentions_chunk_id   ON entity_mentions (chunk_id);
CREATE INDEX IF NOT EXISTS idx_mentions_sitemap_id ON entity_mentions (sitemap_id);
