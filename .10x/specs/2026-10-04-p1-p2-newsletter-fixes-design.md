# P1/P2 bug fixes and a real newsletter — design (2026-10-04)

**Feature slug:** `p1-p2-newsletter-fixes`
**Role for this work:** dev (CLAUDE.md). Each ticket ends `status: ready-for-qa` with Done-when evidence on the ticket; dev never closes.
**Owner decisions (2026-10-04):** fix all open P1 and P2 bugs; show the newsletter; produce quality code; **summaries move to the DeepSeek endpoint** (OPS-20 option a-variant: `OPENAI_*`, deepseek-v4-flash, thinking disabled).

## Scope
| Ticket | Sev | Work |
|---|---|---|
| OPS-20 #136 | P1 | Summarizer on the OpenAI-compatible endpoint; `DAILY_API_CALL_LIMIT` documented against the real per-model quota (Gemini 20/day free, DeepSeek endpoint separate count); one WARNING per day on the first daily-quota 429 |
| SYS-68 #216 | P2 | Summaries produced vs fallen back are counted, shown in the digest footer and in the `newsletter_digests` row, ERROR below 80%, API calls stop after the first quota 429 |
| SYS-67 #215 | P2 | Measure on 3 days of digests, then fix fragmentation (same story split) and contamination (unrelated stories merged) |
| SYS-63 #204 | P2 | One shared boilerplate cleaner in the base `Crawler` applied to every extractor |
| SRC-56 #205, SRC-03 #14 | P2 | **Not fixable in code** (Cloudflare fingerprint blocks; owner decisions). Left open, reported. |

Out of scope: OPS-38 (scheduling the newsletter), P3s, ready-for-qa tickets, repairing stored rows (SYS-63 repair needs a separate owner decision: it changes chunk text and re-embeds).

## Design
### 1. Summarizer (OPS-20 + SYS-68)
- New `newscrawler/core/summarizer.py`: a small interface `summarize(prompt) -> str` with `OpenAICompatSummarizer` (chat completions, `temperature=0.2`, `extra_body={"thinking": {"type": "disabled"}}`, bounded `max_tokens`) and `GeminiSummarizer` (existing behaviour). Provider chosen by `NEWSLETTER_LLM_PROVIDER` (`openai` default when `OPENAI_API_KEY` is set, else `gemini`, else none).
- `QuotaExhausted` is raised for a daily-quota error (HTTP 429 / `RESOURCE_EXHAUSTED`); any other failure is a plain error.
- Calls are counted in `api_usage_log` under the model name, only after the API answered (OPS-09's rule), through the existing knowledge datasource counters.
- `NewsletterGenerator` records a `SummaryStats` (summarized, fallback, total, provider, stop_reason). After a `QuotaExhausted`, or after N consecutive plain errors, it stops calling and marks the remaining clusters as fallback (not N failed API calls).
- Output: the digest footer line `Ringkasan AI: 96/96 (deepseek-v4-flash)` or `Ringkasan AI: 0/96 — kuota harian habis; sisanya hanya daftar judul`. The same numbers are stored in the `newsletter_digests.categories` JSON under the reserved key `_summaries` (no migration, no DB schema change). Below `NEWSLETTER_MIN_SUMMARY_SHARE` (0.8) the generator logs an ERROR and the crawl_log row carries a note; `generate_newsletter` still returns the path.

### 2. Clustering (SYS-67)
Measure first: a read-only script computes, for 3 days, clusters at distances 0.30–0.45 with and without a title-token merge pass, and counts fragments and contaminated clusters by hand-read of the shown ones. Candidate fixes in order: cluster on `title + L1` instead of L1 alone; a merge pass for shown clusters sharing ≥ 2 rare title tokens; cap one story at 2 slots per section. The chosen setting must meet ≤ 1 fragment per section and ≤ 1 contaminated cluster per day on those days. Result goes in EXPERIMENTS.md.

### 3. Boilerplate cleaner (SYS-63)
`clean_body_paragraphs()` in `core/utils/utils.py`, called once from `Crawler._get_news_details` for every extractor's output before `_has_usable_text`. Drops whole paragraphs matching a fleet vocabulary (`baca juga|baca selengkapnya|lihat juga`, `advertisement`, `gulir untuk`, `scroll to continue`, `[gambas:`, `tautan telah disalin`, `berita selengkapnya`, "ikuti … google news / whatsapp channel") and trailing editor initials. Conservative: anchors at paragraph start so a sentence that mentions "google news" in prose survives. A unit test per affected source on saved HTML where fixtures exist, and a fleet test that the cleaner leaves a normal paragraph untouched.

### 4. The newsletter the owner asked to see
After OPS-20 and SYS-68 land: run `task=newsletter` for the most recent complete day. This **writes `digests/<date>.md` and upserts one `newsletter_digests` row** (a production DB write): ask the owner before running. Until then, produce the file without the DB row via the generator's offline path if one is cheap; otherwise ask.

## Testing strategy
Unit tests with fakes: summarizer raising `QuotaExhausted` → exactly one API call, footer 0/N, ERROR once; summarizer success → N/N; mixed. Clusterer tests on synthetic vectors for the merge pass. Cleaner tests on saved HTML. Register mutants in `qa_mutation_runner.py` for each guard. Full `tests/unit` and `tests/integration` green before each ready-for-qa label.

## Risks
- DeepSeek endpoint availability/latency: ≤ 96 calls, serial or small pool; timeouts set; failure degrades to headlines with the count visible.
- Cleaner over-stripping real prose: anchored patterns, tests on negative cases, EXPERIMENTS before/after on a scheduled run.
- Secrets: `OPENAI_API_KEY` never logged (reuse the existing redaction habits).
