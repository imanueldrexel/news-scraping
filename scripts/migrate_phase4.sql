-- Phase 4: RAG Search — Full-text search on chunks
-- Uses 'simple' configuration for portability (no extra extensions needed).

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('simple', text_content)) STORED;

CREATE INDEX IF NOT EXISTS idx_chunks_fts ON chunks USING GIN(fts_vector);
