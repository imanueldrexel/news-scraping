# ADR-003: Knowledge extraction behind a provider, bounded by dollars and the provider's peak window

**Status:** Proposed (the code is in; the default stays Gemini until the owner confirms DeepSeek on #136 after the bake-off)
**Date:** 2026-10-04
**Feature:** sys-39-knowledge-extraction
**Author:** 10x-Team (SDE); provider and prices from the owner 2026-10-04

## Context
`KnowledgeExtractor` called the Gemini SDK directly, took the call budget from `GEMINI_DAILY_CALL_LIMIT` (20, the free tier) and ran one batch of 50. `knowledge_extracted = 0` for all 84,606 articles. The owner decided the KB covers all news, on DeepSeek via SumoPod: input $0.15 / $0.30 and output $0.60 / $1.20 per 1M tokens (off-peak / peak; peak is UTC weekdays 01:00-04:00 and 06:00-10:00). About 4,000 articles a day is ~$1.2 off-peak; the backlog is ~$25.

## Decision
- `core/extraction_provider.py`: an `ExtractionProvider` (`complete(prompt) -> Completion(text, input_tokens, output_tokens)`, `name`, `priced`) with an OpenAI-compatible and a Gemini implementation, chosen by `KNOWLEDGE_LLM_PROVIDER`. **Empty means Gemini**: moving to the priced provider spends money, so it is a deliberate config change, not a side effect of `OPENAI_API_KEY` being present (the summarizer's rule is the opposite because its calls were already being made there).
- The OPS-09 boundary is the provider's contract: `ProviderTransientError` only when no response arrived; `ProviderQuotaExhausted` (a per-day 429) is a subclass that ends the run. `GeminiTransientError` stays as an alias.
- A run asks for batches until the queue is empty or `KNOWLEDGE_MAX_PER_RUN`, and stops before the next call on: the peak window (`core/peak_hours.py`, unless `KNOWLEDGE_ALLOW_PEAK`); the day's `api_usage_log.cost_usd` reaching `KNOWLEDGE_DAILY_COST_LIMIT_USD` (priced provider) or the call count reaching `GEMINI_DAILY_CALL_LIMIT` (unpriced); a daily quota; `KNOWLEDGE_MAX_CONSECUTIVE_ERRORS` failed calls in a row.
- `api_usage_log` gains `input_tokens`, `output_tokens`, `cost_usd` (`migrate_api_usage_tokens.sql`); the run's totals and stop reason ride on the `crawl_log` row's note.
- Catch-up order: attempts ascending (SYS-19: a once-failed article sinks), then finance topics, then newest.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Default to DeepSeek whenever its key is set | The KB fills without a config step | Silent spend; the bake-off has not passed | Owner confirms on #136 first |
| Count dollars in a new table | Cleaner | Another migration and join | Three columns on the row that already holds the day's count |
| Parallel workers | 4k articles in minutes | DB sessions per article, unknown provider rate limits | Serial first; measure wall clock in the bake-off |
| Model Chinese public holidays as off-peak | Exact pricing | Needs a holiday calendar | Costs only waiting time, never money |
| Finance-first before attempts | Strict priority | A poison finance article starves everything for 3 runs | Keeps SYS-19's rule |

## Consequences
- Positive: provider is configuration and testable with a fake; spend is bounded and visible per day; the 20/day Gemini cap no longer gates DeepSeek.
- Negative: the extractor now has a loop and four stop conditions; `GEMINI_DAILY_CALL_LIMIT` and `KNOWLEDGE_DAILY_COST_LIMIT_USD` are two budgets to explain.
- Risks: the cost guard sees only this model's `cost_usd`; the summarizer's calls on the same model record calls but no dollars (small: ~100 calls a day). A provider whose price list changes needs the four `KNOWLEDGE_PRICE_*` variables updated.

## Dependencies
- `migrate_api_usage_tokens.sql` must be applied to `newsaggregator` before any extraction or newsletter run on this code (the usage insert names the new columns). Owner-approved DB write, after a backup.
- Constrains the SYS-39 bake-off (`scripts/experiments/bakeoff_extraction.py`) and OPS-20's Done-when.
