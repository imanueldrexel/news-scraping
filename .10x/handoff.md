# Current Handoff

## From: SDE (dev) -> To: QA
**Date:** 2026-10-04
**Phase:** Implementation (fixes) -> Verification

### Context
QA's four findings are fixed (detail: `decisions/sde/p1-p2-newsletter-fixes.md`, section "QA feedback fixed"). Ready for QA: #219 SYS-71, #220 SYS-72, #221 DBT-51, #222 DBT-52, and re-labelled #216 SYS-68, #215 SYS-67, #204 SYS-63. #136 OPS-20 is NOT labelled (needs the owner's provider choice).
Commits: 02a4312 (DBT-52), 2cf4f47 (SYS-71), a5f9001 + 186acea (SYS-72), ae58c86 (DBT-51), ddc76b1 (mutants), plus the EXPERIMENTS commit.

### What to test
- `tests/unit` 1,827 passed, `tests/integration` 156 passed (dev run). Mutants: `qa_mutation_runner.py sys71_* dbt51_* sys72_* sys63_baca_juga_dropped` all KILLED; write your own for the `_DAILY` regex and the retry bound.
- SYS-72: re-run your four probes; also compare old vs new `is_boilerplate_line` over stored lines (my comparison found 81 losses my percentages hid).
- #204: the 19:00 crawl is the first run of the final cleaner; re-run the per-source residue table on its rows (<= 2%).
- Digest: `digests/2026-10-03.md` (94/94 summaries). A stray partial-day row `2026-10-04` (236 articles) exists in `newsletter_digests` plus `digests/2026-10-04.md`: `task=newsletter` with no date digests today.

### Open Questions
- Owner: delete the stray 2026-10-04 digest row/file, or keep it? (Whether a later run for the same date replaces the row is untested.)
- Owner: OPS-20 provider choice; SYS-73 repair approval (dry run first).

---

## Handoff History
- 2026-10-04 QA -> SDE: fix SYS-71 first, then SYS-72, DBT-51, DBT-52; owner approved task=newsletter, SYS-67 as scoped, SYS-63 repair after SYS-72.

- 2026-10-04 planning -> SDE: P1/P2 fixes + newsletter (spec + ADR-001, ADR-002).
- 2026-10-04 brainstorming -> QA: verification of 9 ready-for-qa tickets (baseline done, see decisions/qa). QA pass is paused while dev work runs; scheduled-run evidence still pending.
- 2026-10-04 init-project -> first active role: state initialized.
