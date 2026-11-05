# QA pass 2026-11-05: SYS-197 (#427) and SYS-198 (#428), NLI eval set + shadow

**Scope (owner):** the fix is the local `dev` commits with `Refs #N`; there are no PRs. Baseline is the parent of the first implementing commit (1e10a2e^). SYS-40/82/83 and OPS-42 were skipped: they are held on owner reads.

**Verdicts:** both qa-failed.
- SYS-197: #431 (major, narrowed by ADR-030), #432 (major: 9 label_ok=n pairs still scored), #433 (major: no lexicon-gate comparison), #434 (minor: golden c6/h3 mislabelled).
- SYS-198: #435 (closed not-a-defect, ADR-030 d1), #436 (major: preview/replay write `nli_shadow`), #437 (major: MAX_PREMISES=60 cuts the alur quotes, 2 of 5 live stories), #438 (minor: a missing model warns per sentence), #439 (minor: the byte-identical integration test is missing).
- Held: live rows 11-04 (20/20, +124.5 s) and 11-05 (14/14, about +101 s); migration on both DBs; `tests/unit` 4063 passed.

**Owner decisions (ADR-030):** whole-sentence hypothesis; natural set in SYS-200, gated on #436/#437; families kept, with the leak gated by wrong-premise AUC <= 0.65 per type. QA measured the AUC: arm A 0.52-0.59, arm B v2 0.51-0.62. It holds.

**Lessons**
- An artefact check over contrastive pairs must keep each seed's pairs in one fold. Shuffled folds put the twins on both sides, which drives the score to chance and hides the leak.
- A dataset-level leak can be survivable at the model level. Measure with the wrong-premise control before discarding data.
- A "read-only" tool that subclasses the real datasource inherits every new write method. Check the overrides whenever a datasource gains a `save_*`.

QA tests: `tests/qa/test_qa_sys197.py`, `tests/qa/test_qa_sys198.py` (not committed, by QA rule).
