# RAG search redesign: patterns and standards (2026-10-07)

## Reuse, don't re-derive
- **Dates, outlet names, section names:** `core/newsletter_copy` (`tanggal_pendek`, `outlet`, `SECTION_NAMES`). The page adds no second table of any of them.
- **Number check:** `core/story_summary.unsupported_number`, the same value comparison as the newsletter (SYS-87).
- **Provider:** `core/summarizer.build_summarizer` plus the new `complete()`. Pricing: `core/peak_hours.cost_usd`.
- **Usage rows:** `SQLAlchemyKnowledgeDataSource.increment_api_call_count` / `get_today_api_usage`.

## Standards for the web layer
- **Copy:** templates hold no literal reader text. Every string is `copy.X` from `core/web_copy.py`, and a unit test parses the templates to enforce it.
- **Escaping:** no `| safe` / `Markup(` on any value derived from scraped text or model text. A test greps the templates.
- **Pure logic:** parsing, prompt building and filter parsing are pure functions, unit-tested without FastAPI or a DB. Routes stay thin.
- **Blocking work** (DB, FAISS, LLM) runs in `run_in_threadpool` (DBT-15). The routes are async.
- **Logging:** each question logs one INFO line: `rag retrieve ms=… hits=… filters=…`, then `rag answer status=… ms=… tokens=…/… cost=…`. Exceptions are logged at WARNING/ERROR with their type, never rendered.
- **Constants:** the new variables go in `core/constants.py` under "RAG Search", read at import time like the others, and in OPERATIONS.md's table.
- **Accessibility:**
  - every control has a visible `<label>` (or `aria-label` for icon-free text buttons);
  - focus is visible;
  - colour tokens reach >= 4.5:1 for text, which a unit test checks for the light and the dark set.

## Tests (where each guard lives)
| Concern | Test file |
|---|---|
| answer parsing, cleanup, citations, number check, prompt | `tests/unit/test_rag_answer.py` |
| answer states with a fake Summarizer, usage key, cap, no-hit no-call | `tests/unit/test_rag_answer_states.py` |
| filters: parsing, SQL params, metadata-driven filtering | `tests/unit/test_rag_filters.py` |
| rendered page and fragments: escaping, copy, no internal names, labels, thread attributes | `tests/unit/test_rag_page.py` |
| colour contrast tokens | `tests/unit/test_rag_contrast.py` |
| summarizer `complete()` | `tests/unit/test_summarizer.py` (existing file, extended) |
| topic filter on a seeded DB through the real FTS + metadata SQL | `tests/integration/test_rag_filters_live.py` |

Mutants for each fix are registered in `scripts/experiments/qa_mutation_runner.py` (`sys9x_*`, `sys10x_*`) and run in a scratch worktree.
