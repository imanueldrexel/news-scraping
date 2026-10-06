# RAG search redesign: verification (2026-10-07, dev-side QA for the 10x gate)

Report: `.10x/reviews/2026-10-07-qa-report.md`. Independent QA still closes the tickets (repo rule).

## Strategy
- **Pure logic** (prompt, cleanup, citations, number check, filters): unit tests without FastAPI or a DB.
- **States:** a fake Summarizer and a fake usage ledger drive every branch.
- **Page:** FastAPI TestClient with a fake processor.
  - Rendered-HTML guards: escaping, internal names, dates, labels.
  - Template-source guards: no `| safe`, no literal reader text.
- **Colours:** contrast computed from the CSS tokens in both themes.
- **SQL:** an integration test on `newsaggregator_test` through the real FTS and metadata queries.
- **Live:** a replay of 10 questions on production through the JSON API; one Gemini question; screenshots; a keyboard-only e2e in headless Chrome over CDP.
- **Mutants:** 42, one or more per ticket, registered in `qa_mutation_runner.py`; 42/42 killed.

## Gaps left for independent QA
- No screen reader and no axe.
- The screenshots are of snapshots built from real server fragments, not of an interactive session; the e2e covers the interaction instead.
