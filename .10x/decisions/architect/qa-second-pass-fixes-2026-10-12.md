# Architect: dev fixes of QA's second pass (2026-10-12)

Spec: `specs/2026-10-12-qa-second-pass-fixes-design.md`. ADR-013, ADR-014, ADR-015.

## Components touched
- `newscrawler/web/query_processor.py`:
  - `candidates` gains the subject gate on the window path (ADR-013);
  - one new SQL helper `_holds_subject(kq, texts)` built on `_word_tests`, the same tokenizer as `_coverage`.
- `newscrawler/web/keywords.py`: `KeywordQuery.subject` (the names if any, else the anchors). A pure property, so the rule lives next to anchors and names.
- `newscrawler/web/followup.py`: `check` refusal/list rejection (SYS-143), the `_NOT_REFERENCES` adverbs (SYS-144), `KEPT_THREAD` in `resolve` (SYS-145, ADR-014).
- `newscrawler/tools/store_repair.py` (new, ADR-015) and the four repair scripts.

## Failure modes
- The subject test's SQL fails: the gate is closed and only keyword-retrieved window hits lead, with a warning. The floor and the fill still run, and the reader still gets cards.
- No keyword query: the floor decides, as in ADR-012.
- A refusal or list from the rewrite: the fallback runs, and the call is still counted.

## Boundaries
- No change to the retrievers, the scores, the floor, the answer prompt or the API.
- The DBT-67 move changes no SQL and no write order.
