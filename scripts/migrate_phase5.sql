-- Phase 5: Monitoring — Crawl log table

CREATE TABLE IF NOT EXISTS crawl_log (
    log_id        BIGSERIAL PRIMARY KEY,
    website       TEXT NOT NULL,
    task          TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    article_count INT,
    error_msg     TEXT,
    started_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crawl_log_website ON crawl_log(website);
CREATE INDEX IF NOT EXISTS idx_crawl_log_started ON crawl_log(started_at DESC);
