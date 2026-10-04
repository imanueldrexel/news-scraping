# QA pass 2026-10-04 (night): P1/P2 against the tickets' wording

Full report: `.10x/reviews/2026-10-04-night-qa-report.md`. Summary: closed OPS-35, OPS-37, SYS-71, SYS-72, SYS-67 (after a send-back), SYS-68, SYS-63, SYS-69, SYS-65, SYS-75, DBT-53, DBT-54, DBT-50, DBT-19, DBT-22, SYS-76, SYS-77; held for scheduled-run evidence: SRC-57 (3 runs), SYS-64 (7 days), SYS-66 (cooldown), OPS-38 (3 digests), SYS-78 (next extraction run); held for the owner: OPS-36 (confirm the two Telegram messages), SYS-40 (read a digest), OPS-20 (see report addendum). Independent mutation runs in clean `git archive` copies: 69/69 + 61/61 + 8/8 killed (4 stale ones retargeted first; 270 registered mutants now match exactly once).

New tickets filed by QA: DBT-53 #226, DBT-54 #227, SYS-76 #228, SYS-77 #229, SYS-78 #230, SRC-58 #231, OPS-39 #232.

Lessons: (1) a unit suite with no guard can run a script against production when a guard is mutated; the guard is now in `tests/unit/conftest.py`. (2) A mutant defined by a text pattern goes stale when the code is refactored; check that every registered mutant still matches exactly once before trusting "all killed". (3) Read real output, not only agreement scores. (4) Read the full 429 body before saying a quota is spent.
