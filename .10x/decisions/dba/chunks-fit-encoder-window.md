# Chunks fit the encoder window (SYS-109) -- DBA

- **DBT-64:** `CREATE INDEX IF NOT EXISTS idx_mentions_chunk_id ON entity_mentions (chunk_id)` and `idx_mentions_sitemap_id ON entity_mentions (sitemap_id)`.
  - Every `DELETE FROM chunks` checks the FK `entity_mentions.chunk_id` by a sequential scan of 230,061 rows: 17,222 rows took 9 min on 2026-10-08.
  - The settle/repair scripts delete mentions `WHERE sitemap_id = ANY(...)`, which has no usable index either (the unique key leads with entity_id).
  - Plain `CREATE INDEX` on 230k rows takes seconds; no CONCURRENTLY needed under the run lock.
- **Volume:** chunks L2 373k → ~800k rows. `fts_vector` is generated and its GIN index grows with it.
- **After the rebuild:** `ANALYZE chunks`. `web/keywords.DocFrequency` reads `pg_stats.most_common_elems`; its shares move from paragraphs to windows. The ADR-006 thresholds (anchor 3%, name 10%) are shares, so they stay meaningful.
- **Backups:** a fresh `backup_db.py` dump before the run; the run's own JSON of the deleted L2 rows (enough to restore them without a full DB restore).
