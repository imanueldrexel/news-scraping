-- SYS-19: track knowledge-extraction attempts per article so a poison article
-- (unparseable Gemini response, or a response whose shape crashes _process_extraction)
-- stops being re-selected by get_articles_pending_extraction forever. Without this,
-- knowledge_extracted stays 0 and the newest-first query re-picks it every run,
-- burning one Gemini call each time and starving every other pending article once
-- enough poison articles accumulate among the newest rows.
--
-- Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_knowledge_extract_attempts.sql

ALTER TABLE articles ADD COLUMN IF NOT EXISTS knowledge_extract_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS last_extract_error TEXT;

CREATE INDEX IF NOT EXISTS idx_articles_extract_attempts ON articles(knowledge_extract_attempts);
