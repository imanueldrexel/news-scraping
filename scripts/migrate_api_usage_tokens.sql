-- SYS-39 (#125): api_usage_log counted calls only. Extraction now runs on a priced
-- provider (DeepSeek via SumoPod) whose budget is dollars, not requests, so each
-- day's row also carries the tokens the provider reported and what they cost at
-- the window's price (peak/off-peak, see core/peak_hours.py). Existing rows keep
-- zeros: their tokens were never recorded.
--
-- Idempotent. Usage:
--   psql -U postgres -d newsaggregator -f scripts/migrate_api_usage_tokens.sql

ALTER TABLE api_usage_log ADD COLUMN IF NOT EXISTS input_tokens  BIGINT        NOT NULL DEFAULT 0;
ALTER TABLE api_usage_log ADD COLUMN IF NOT EXISTS output_tokens BIGINT        NOT NULL DEFAULT 0;
ALTER TABLE api_usage_log ADD COLUMN IF NOT EXISTS cost_usd      NUMERIC(12,6) NOT NULL DEFAULT 0;
