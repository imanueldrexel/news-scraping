# ADR-001: Newsletter summaries via a pluggable summarizer with explicit degradation accounting

**Status:** Accepted
**Date:** 2026-10-04
**Feature:** p1-p2-newsletter-fixes
**Author:** 10x-Team (Architect + Staff Engineer); provider chosen by the owner 2026-10-04

## Context
`NewsletterGenerator.summarize_cluster` calls Gemini directly. The project's Gemini free tier allows 20 requests/day/model (OPS-20), one digest needs up to 96, so the 2026-09-28 digest has 0/96 real summaries and nothing says so (SYS-68). The owner chose the existing OpenAI-compatible DeepSeek endpoint (already used by the SYS-36 labeller) for summaries.

## Decision
Introduce `newscrawler/core/summarizer.py` with an interface and two implementations (OpenAI-compatible, Gemini). The generator depends on the interface, counts summarized vs fallback clusters, stops calling after the first quota error or a run of consecutive errors, and reports the count in the digest footer and in the `newsletter_digests.categories` JSON under the reserved key `_summaries`. Calls are counted in `api_usage_log` under the model name after a response.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Keep Gemini, summarize only the top ~20 clusters | No new dependency | Thin newsletter, still silent unless SYS-68 added | Owner chose DeepSeek |
| Swap the Gemini client for the OpenAI client inline | Smallest diff | Hard-wires one provider again; untestable without the SDK | Same coupling that caused the bug |
| New `summary_stats` column on `newsletter_digests` | Cleaner schema | Needs a hand-written migration and a production DB write | JSON key avoids a migration; revisit if more consumers appear |
| Gemini paid tier | No code change for quota | Needs billing set up by the owner | Not chosen |

## Consequences
### Positive
- 96 summaries per digest fit the endpoint; degradation is visible in the file, the row and the log.
- Provider swap is a config change; fakes make the generator testable without a network.

### Negative
- `categories` JSON now holds one non-topic key (`_summaries`); consumers must skip keys starting with `_` (none exist today).
- A second SDK path (`openai`) is on the newsletter code path.

### Risks
- Endpoint outage → whole digest degrades to headlines; mitigated by the visible count and the ERROR below 80%.
- Reasoning model burning tokens: thinking disabled and `max_tokens` bounded, as in the labeller.

## Dependencies
- `openai` package (already pinned), `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL` in `.env`.
- Constrains OPS-38 (scheduling) and SYS-39 (extraction provider bake-off) to reuse the same interface.
