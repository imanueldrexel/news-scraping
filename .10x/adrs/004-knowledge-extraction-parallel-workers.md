# ADR-004: Knowledge extraction calls run on four worker threads; writes stay on one

**Status:** Accepted (CTO decision 2026-10-04 night, on the owner's request to make the P1/P2 work run properly)
**Date:** 2026-10-04
**Feature:** sys-39-knowledge-extraction
**Author:** 10x-Team (CTO + Architect + SDE)

## Context
ADR-003 left extraction serial: ~3 s per article. 4,000 new articles a day is ~3.5 h; the 84,606-article backlog is ~73 h, i.e. the queue would never empty while new articles keep arriving. The bake-off ran 200 articles on 4 workers with 0 errors and 0 rate-limit responses (165 s, p95 latency 5 s).

## Decision
`KnowledgeExtractor._extract_batch` submits provider calls to a `ThreadPoolExecutor` of `KNOWLEDGE_WORKERS` (default 4; 1 is the old serial behaviour) with at most that many in flight. The calling thread alone runs the stop checks (peak window, budget), the counters, `increment_api_call_count`, entity writes and `mark_article_extracted`, and consumes finished calls in article order. A stop (peak, budget, quota, consecutive failures) prevents new submissions; calls already in flight are consumed and recorded (they are paid for). Overshoot is at most `workers - 1` calls, each ~$0.0003.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Stay serial | No concurrency | Cannot clear the backlog or keep up | Defeats the owner's decision to cover all news |
| Workers also write to the database | Fully overlapped | One session per worker, interleaved `upsert_entity` counters (SYS-20), harder rollback per article | The DB work is ~ms next to a ~3 s call; not the bottleneck |
| Many more workers (16+) | Faster | Rate limits unknown above 4; a stop overshoots more | Measure first; the setting is an env var |
| asyncio | Lighter than threads | The SDK path and the datasource are synchronous | A rewrite for no gain |

## Consequences
- Positive: ~55 minutes per 4,000 articles; the backlog clears in about a day of runs instead of three days of one serial process.
- Negative: stop conditions can overshoot by up to `workers - 1` calls; log lines of different articles interleave less predictably (the consumer order is kept).
- Risks: a provider that rate-limits above some concurrency returns 429s: a per-day quota stops the run; a per-minute one is retried once by `call_guarded`, and 5 failures in a row stop the run. Lower `KNOWLEDGE_WORKERS` if that ever shows in `crawl_log`.

## Dependencies
- ADR-003 (provider, budget, peak guard); OPS-09 and SYS-19 boundaries unchanged.
