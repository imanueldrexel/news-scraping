# p1-p2-newsletter-fixes — DBA

### 2026-10-04 — No schema change
- `newsletter_digests.categories` (JSONB) gains the reserved key `_summaries` = `{total, summarized, provider, stopped, groups_ok, groups_failed}`. No migration, no new column; readers skip keys starting with `_`. Revisit a column (`summary_stats jsonb`) if a second consumer appears.
- `api_usage_log` now also counts the OpenAI-compatible model's calls (by model name) from the newsletter. The preview script writes neither.
- No production DB write was made in this work: every live check was read-only.
