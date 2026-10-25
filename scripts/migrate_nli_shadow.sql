-- SYS-198 (#428, ADR-024): the NLI faithfulness check runs in shadow over the story arcs' sentences.
-- One row per arc sentence per edition: the sentence, the gate families it matches, and the NLI
-- verdict against the story's cited quotes. Nothing reads this table to decide an edition.
-- p_* are NULL when there is no verdict (model unavailable, time budget spent).
--
-- Idempotent. Usage (prefer scripts/migrate.py):
--   psql -U postgres -d newsaggregator -f scripts/migrate_nli_shadow.sql

CREATE TABLE IF NOT EXISTS nli_shadow (
    shadow_id        BIGSERIAL PRIMARY KEY,
    edition_date     DATE      NOT NULL,
    story_id         INT       NOT NULL,
    field            TEXT      NOT NULL,
    sentence         TEXT      NOT NULL,
    error_tags       TEXT,
    premise_ids      JSONB,
    best_premise     TEXT,
    p_entail         REAL,
    p_neutral        REAL,
    p_contradict     REAL,
    model_revision   TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nli_shadow_date ON nli_shadow (edition_date);
