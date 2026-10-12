# Architect: QA + senior ticket list, 2026-10-12

Spec: `.10x/specs/2026-10-12-qa-senior-fixes-design.md`. ADRs 010, 011, 012.

## Components touched
- `newscrawler/web/followup.py` (new): prompt, output check, fallback rule. Pure functions plus one `rewrite(summarizer, thread, question)` that never raises.
  - `QueryProcessor.retrieve/candidates` take the resolved retrieval question and its cue.
  - `keywords.terms(questions)` takes per-question names (SYS-140).
- `newscrawler/tools/source_worker.py`: the job carries `timeout_s`.
  - `CrawlerAPI.crawl_website(..., deadline=None)` → `CrawlerServiceImpl.crawl_newsdetails(..., deadline=None)`, which checks the batch loop against the deadline.
- `data_flow_repository_impl.save_chunk_data`: a stale L2 level (rows over `CHUNK_MAX_TOKENS`) is replaced, not kept (SYS-137).
- `check_store_consistency.py`: `l2_over_max_tokens`.
- `QueryProcessor` re-rank: the week window and the relative relevance gate (ADR-012).

## Failure modes
- **Rewrite down** (no key, cap, timeout, bad output): deterministic fallback, logged. The page never errors for it.
- **Soft deadline misjudged** (a batch longer than the margin): the hard kill remains, as before.
- **SYS-137 guard** deletes vectors inside the deferred block. Like SYS-54, a kill before the flush leaves rows without vectors, and the existing heal covers them.
