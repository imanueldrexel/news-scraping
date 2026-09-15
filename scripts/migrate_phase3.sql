-- Phase 3: Newsletter Digest — Schema Migration

CREATE TABLE IF NOT EXISTS newsletter_digests (
    digest_id     BIGSERIAL PRIMARY KEY,
    digest_date   DATE NOT NULL UNIQUE,
    file_path     TEXT NOT NULL,
    cluster_count INT NOT NULL DEFAULT 0,
    article_count INT NOT NULL DEFAULT 0,
    categories    JSONB,
    source_ids    JSONB,
    generated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    generation_ms INT
);

ALTER TABLE sitemaps ADD COLUMN IF NOT EXISTS cluster_id INT;
