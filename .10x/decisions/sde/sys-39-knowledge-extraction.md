# sys-39-knowledge-extraction — SDE

### 2026-10-04 (evening) — SYS-39 #125 built, not closed (ADR-003)
- `core/extraction_provider.py`: `ExtractionProvider` (OpenAI-compatible with thinking off + JSON mode; Gemini), `KNOWLEDGE_LLM_PROVIDER` (empty = gemini; the switch to the priced provider is a deliberate config change). `ProviderTransientError` (no response; OPS-09) and `ProviderQuotaExhausted` (per-day 429, both providers; ends the run). `GeminiTransientError` is an alias.
- `core/peak_hours.py` (UTC weekday 01-04 and 06-10, weekends off-peak; per-call price from `KNOWLEDGE_PRICE_*`).
- `KnowledgeExtractor.extract_all`: loops until the queue is empty / `KNOWLEDGE_MAX_PER_RUN` (6000); before each call stops on peak (unless `KNOWLEDGE_ALLOW_PEAK`), the day's `cost_usd` >= `KNOWLEDGE_DAILY_COST_LIMIT_USD` (priced) or call count >= `GEMINI_DAILY_CALL_LIMIT` (unpriced), a quota error, or `KNOWLEDGE_MAX_CONSECUTIVE_ERRORS` failures in a row; a `seen` set stops re-trying a transiently failed article in one run. `ExtractionResult` carries tokens, cost, stop reason; `note()` goes on the `crawl_log` row.
- `api_usage_log.input_tokens/output_tokens/cost_usd` (`migrate_api_usage_tokens.sql`, in `scripts/migrate.py`; applied to `newsaggregator_test` ONLY). Pending query: attempts, then finance topics, then newest.
- Bake-off tooling `scripts/experiments/bakeoff_extraction.py` (fixture / run / score), fixture and three runs committed under `tests/fixtures/`.
- Tests: unit 1,976 / integration 165 pass; 24 mutants killed; the Gemini daily-quota stop added after the bake-off showed Gemini's 429 as "transient".

### Result (EXPERIMENTS 2026-10-04)
DeepSeek: 200/200 answered, 0 parse failures, 0 429 at 4 workers, 791/335 tokens per article, $0.32 per 1,000 off-peak (~$1.3/day, ~$27 backlog), run-to-run pooled F1 0.960 (Gemini self-agreement 0.53), event_type agreement 0.76. The 0.85-vs-Gemini-reference gate cannot run on the free tier (6 of 20 Gemini calls answered).

### Deviations
- The default provider stays Gemini (the handoff said "strategy chosen by env var"; I chose not to make a key's presence spend money).
- `KNOWLEDGE_BATCH_SIZE` now means "per query", not "per run" (documented).

### Open / needs the owner (all on #125 and #136)
1. Choose how to settle the 0.85 gate (hand-check 50 rows / accept repeatability+cost / Gemini billing).
2. Approve applying `migrate_api_usage_tokens.sql` to `newsaggregator` after a backup. **Until then do not run `task=extract_knowledge` or `task=newsletter` on this code against production** (the usage insert names the new columns; the summarizer's counter swallows the error, the extractor's does not).
3. Set `KNOWLEDGE_LLM_PROVIDER=openai`, schedule an off-peak run (weekend for the backlog; raise the cost limit to ~30 for that run).
### Tech debt created
- Extraction is serial (~3 s per article, ~3.5 h for 4,000); parallel workers and a rate-limit probe above 4 workers are not done.
- `GeminiProvider` keeps the model's default thinking (OPS-20 found 73% of its output tokens are thinking); not changed because Gemini is only the fallback.

### 2026-10-04 (late evening) — owner decisions, executed
1. **SYS-39 gate: accepted on evidence** (repeatability 0.960, 0 parse failures, $0.32/1,000, reversible env switch, gold-set hand check 96-98%). No hand-check, no Gemini reference. `KNOWLEDGE_LLM_PROVIDER=openai` is still NOT set in `.env`: setting it and scheduling the extraction run are the next steps (off-peak; backlog needs `KNOWLEDGE_DAILY_COST_LIMIT_USD` ~30 for one run).
2. **Production migration applied** after a verified dump (`backups/pg_dump/newsaggregator_20261004T133211Z.dump`, 246 MB): `api_usage_log` has the 3 new columns, 9 existing rows intact.
3. **OPS-38: 12:00, registered** as "NewsAggregator Newsletter" (first run 2026-10-05 12:00, digests 2026-10-04 and replaces the stray partial row).
4. **SYS-73: per source, DETIK first, after QA closes SYS-75.** The apply path is the next code to write (dry-run per source first).

