-- DBT-09: enforce one `chunks` row per (sitemap_id, chunk_level, chunk_index).
--
-- Production held 1,035 duplicate rows (VIVA/GRIDID/PIKIRANRAKYAT) with distinct
-- embedding_ids -- each is a real, separate FAISS vector too. Run
-- scripts/dedupe_chunks.py FIRST (dry-run, then for real) to remove the
-- duplicate rows and their orphaned FAISS vectors; this migration only adds
-- the index and will fail with a "could not create unique index" error if any
-- duplicates remain.
CREATE UNIQUE INDEX IF NOT EXISTS chunks_sitemap_level_index_uq
    ON chunks (sitemap_id, chunk_level, chunk_index);

-- Verify: should return 0.
-- SELECT COUNT(*) FROM (SELECT 1 FROM chunks GROUP BY sitemap_id, chunk_level, chunk_index HAVING COUNT(*) > 1) t;
