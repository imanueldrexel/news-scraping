-- DBT-11 (#46): chunks.article_id has existed since migrate_phase1.sql but was
-- never written -- chunks are saved before the articles row exists (the
-- pipeline runs save_chunk_data, then save_newsdetails_data), so the insert
-- cannot carry it. Since 2026-09-22 save_newsdetails links the batch's chunks
-- right after the articles row commits; this backfills every row written
-- before that. Idempotent: only NULL article_id rows with a matching article.
--
-- Usage (or scripts/migrate.py, which records it in schema_migrations):
--   psql -U postgres -d newsaggregator -f scripts/migrate_chunks_article_id.sql

UPDATE chunks c
SET article_id = a.articles_id
FROM articles a
WHERE c.sitemap_id = a.sitemap_id
  AND c.article_id IS NULL;
