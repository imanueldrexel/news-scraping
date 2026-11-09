# QA pass 2026-10-07 (evening): RAG search redesign (tracker #272) + SYS-103, independent

Report: `.10x/reviews/2026-10-07-qa-independent-report.md`. EXPERIMENTS.md: "2026-10-07 — QA of tracker #272 …".

## Test strategy used
1. **Suites on the live tree** (no mutation there: the 19:00 crawl imports it):
   - unit;
   - integration, with `TELEGRAM_OUTBOX` redirected (OPS-46).
2. **Mutants in an exported copy** (`%TEMP%\q7`):
   - the dev's 67;
   - 40 QA mutants that the dev did not register, picked at the boundaries: the cap `>=`, citation range 0, the top-K cut, the post-filters, the FTS fragments, history admission, the link `rel`, the follow-up's filters, prices;
   - survivors re-run on the full `tests/unit`.
3. **Live, production read-only + ~$0.005 of DeepSeek** on a second uvicorn (:8765):
   - the dev's e2e and snapshot scripts, run independently;
   - a leak/escape scan of every page state;
   - every topic option;
   - a follow-up pair;
   - off-scope and entity questions;
   - an in-process re-rank breakdown (`scripts/experiments/probe_rag_rank_breakdown.py`).
4. **Data checks in SQL** behind every symptom: chunk sizes, recipe residue, kumparan posts, kumparan chrome, today's gold articles.

## Decisions
- **Closed on their Done-when:** SYS-92..SYS-103 and SRC-58. Defects outside a Done-when go into new tickets, not send-backs:
  - SYS-103's Done-when used `fts=20` and the BI-Rate rank as its proxy, and both hold. The proxy hid that keyword-only finds never reach the reader: that is SYS-106.
- **Severity:**
  - P2 for wrong-topic or stale sources that the page presents confidently (SYS-104, SYS-105, SYS-106, SYS-107) and for scope pollution that reaches the top ranks (SRC-60);
  - P3 for hygiene: SYS-108, SRC-61, DBT-61, the test gaps.
- **Not ticketed** (too small; the source's own text):
  - one CNN body with "vdfzxvds";
  - ~20 pre-probe PIKIRANRAKYAT recipe rows.

## Lessons
- A retriever's candidate count is not its contribution. Count the top-5 cards by origin.
- A weighted sum that scores a missing component as 0 hides one retriever's exclusive finds.
- `git archive` copies need the root files `test_repo_hygiene` reads. Otherwise every mutant "dies" at the same test: the identical `1 failed, 1682 passed` on different mutants was the tell. Always run the copy's unmutated baseline first.
