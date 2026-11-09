# RAG search redesign: delivery (2026-10-07)

## Deploy
- **Restart the web app:** `venv\Scripts\python.exe -m uvicorn newscrawler.web.app:app --port 8000`.
  - **One worker only:** sessions and pending turns live in memory.
  - No migration and no new dependency (htmx is vendored in `static/`).
- **Config:** `RAG_LLM_PROVIDER` defaults to `openai`, and `OPENAI_*` is already set for the newsletter. All other new variables have defaults (OPERATIONS.md).

## Rollback
`git revert d2b48d4 ceb73cf`, then restart. The JSON API's request fields changed (`category` → `topic`); nothing in the repo calls it.

## CI
None in this repo. The gate is the suites (unit 2,609 / integration 193) plus the mutants.
