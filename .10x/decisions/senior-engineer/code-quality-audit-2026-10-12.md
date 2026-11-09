# Code-quality audit 2026-10-12: senior engineer

Full report: `.10x/reviews/2026-10-12-senior-code-quality-audit.md`. Scope `c69d34d..f7f8672`.

## Implementation guidance per ticket

- **SYS-140 #322 (P2):** fix it inside the SYS-104 #274 rework, since both change how the thread feeds retrieval.
  - Preferred: `keywords.terms(questions: Sequence[str])`, which judges `name` per question (position > 0 *within that question*) and merges in order: follow-up first, dedup, `MAX_TERMS`. `candidates()` passes `[question] + previous[::-1][:FOLLOWUP_CONTEXT_TURNS]` rather than `text_`.
  - Rejected: lower-casing the appended questions. That would also hide real names ("OJK") in the thread.
  - Test: the `kebijakan` example → `names == []`.
- **SYS-141 #323 (P3):** a three-line change. `vs = self.vs_l2` once, `_l2_positions(vs)`, `vs.index.reconstruct`. Fix the docstring formula. Test it with a stub whose position lookup swaps `vs_l2`.
- **SYS-142 #324 (P3):** measure first, by counting stored L2 rows that are the tail window of a split paragraph with fewer than 20 new words. If material, the last window becomes `words[-max_tokens:]`. Ship it with the next planned re-chunk, never as its own 750k-vector rewrite.
- **DBT-67 #325:** do it after SYS-111 closes. Move the code without changing behaviour; the existing script tests are the safety net. `test_run_lock.py`'s writer discovery must still find the scripts.

## Order for SDE

SYS-111 (P1, sent back) → SYS-104 + SYS-140 together → SYS-141 → DBT-67 → SYS-142 (measurement only until the next re-chunk).
