# RAG search redesign: delivery plan (2026-10-07)

Owner: "do all new tickets from the design critique, now." The provider is decided (DeepSeek), and the mockup needs the owner's approval before the visual build. The plan builds once: the templates and CSS that implement A/B/C are the ones the mockup shows. So the mockup comes first and its CSS becomes `style.css`.

## Sequence (each step: code + tests + mutants; commit `Refs #N`)
| # | Step | Tickets | Depends on |
|---|---|---|---|
| 0 | Mockup (hero state + answered thread, 375/1280, light/dark) → owner approval | SYS-102 step 1 | design |
| 1 | `core/web_copy.py` copy table | SYS-101 (table) | — |
| 2 | `Summarizer.complete()` + `Reply`; `RAG_*` constants | SYS-98 | — |
| 3 | `web/answer.py`: prompt, cleanup, parse, citations, number check | SYS-99, SYS-93 | 1 |
| 4 | `web/filters.py` + `site_stats.py`; `retrieve()` with DB metadata, filters in SQL | SYS-92, SYS-100 | 1 |
| 5 | `answer()` state machine, usage key, cap, no-hit no-call | SYS-94, SYS-98, SYS-99 | 2, 3 |
| 6 | `turn_store.py`, routes `/api/query/form`, `/api/answer/{id}`, JSON `/api/query`, warm-up lifespan | SYS-97, SYS-102 | 4, 5 |
| 7 | Templates + CSS per mockup: thread, cards, states, labels, tokens, dark | SYS-93..97, 100..102 | 0, 6 |
| 8 | Vendor htmx into `static/` (no CDN at runtime) | SYS-102 / security | 7 |
| 9 | Integration test of the topic filter on the seeded DB | SYS-92 | 4 |
| 10 | Live: 1 question on each provider (`api_usage_log` rows); replay of 10 real questions, hand-checked; screenshots at 375/1280 light/dark | SYS-98, SYS-99, SYS-102 | 7 |
| 11 | Docs: OPERATIONS.md variables + runbook, CLAUDE.md RAG paragraph, EXPERIMENTS.md entries; tickets' evidence + `status: ready-for-qa` | all | 10 |

## Risks
- **The mockup may be rejected.** Only the CSS and markup of step 7 are at risk; steps 1-6 are independent of the look.
- **The replay spends money** (~10 DeepSeek calls, < $0.02). The Gemini check spends 1 of the free tier's 20 calls.
- **The owner's own uvicorn runs on :8000 with the old code.** Live checks use :8765, and the owner restarts :8000 afterwards.
- **No browser automation is installed** (no Playwright). Screenshots use headless Edge, and the keyboard pass is manual, partly by the owner.
