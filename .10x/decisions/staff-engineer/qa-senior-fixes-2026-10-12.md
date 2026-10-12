# Staff engineer: QA + senior ticket list, 2026-10-12

- Reuse, don't copy:
  - the rewrite goes through the shared `Summarizer` (`build_summarizer(provider=RAG_LLM_PROVIDER, ...)`) with its own timeout, max_tokens and a no-wait sleep;
  - accounting reuses `QueryProcessor._over_daily_cap` / `_record` under `web:<model>`.
- Reader strings: none are new (the rewrite is not shown). Any copy that becomes visible goes in `core/web_copy.py`.
- Comments state the invariant with a ticket pointer; history goes in commits and EXPERIMENTS.md (senior principle).
- Each seam gets one composed-path test:
  - thread → rewrite → terms/cue;
  - deadline → batch loop → flush;
  - stale level → save → no row over the cap.
- New settings documented in OPERATIONS.md's env table: `RAG_REWRITE_TIMEOUT_S`, `SCHEDULE_SOFT_DEADLINE_MARGIN_S`.
