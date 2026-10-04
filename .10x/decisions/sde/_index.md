# sde decisions — index

## Active features
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) — OPS-20/SYS-68/SYS-67/SYS-63 built; QA feedback SYS-71/72, DBT-51/52 fixed 2026-10-04; ready-for-qa

- [newsletter-digest-quality](newsletter-digest-quality.md) — SYS-69, SYS-65 ready-for-qa; OPS-38 code done, job not registered (owner)
- [sys-39-knowledge-extraction](sys-39-knowledge-extraction.md) — provider/cost/peak guards built (ADR-003); 0.85 gate and prod migration need the owner; not closed
- [body-cleaner-and-repair](body-cleaner-and-repair.md) — SYS-75 fixed (ready-for-qa); SYS-73 dry run done, apply path waits for the owner; DBT-50 ready-for-qa

## Cross-cutting SDE notes
- Edit regexes in `core/utils/utils.py` with the Edit tool, not heredoc Python (escape mangling). Check `git diff -w --stat` equals `git diff --stat` before committing a file with mixed line endings.
- The harness turns backslash escapes inside python heredoc strings into control characters (a lone CR once made git treat OPERATIONS.md as binary). Use Edit/Write for text with backslashes and scan for lone CR afterwards. Never rewrite a whole file's line endings; replace per region (LF first, then CRLF).
- Wait on background work with a Monitor `until grep ...` loop; do not edit tracked files while `qa_mutation_runner.py` runs (it restores by `git checkout`).
