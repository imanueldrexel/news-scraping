# sde decisions — index

## Active features
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) — OPS-20/SYS-68/SYS-67/SYS-63 built; QA feedback SYS-71/72, DBT-51/52 fixed 2026-10-04; ready-for-qa

## Cross-cutting SDE notes
- Edit regexes in `core/utils/utils.py` with the Edit tool, not heredoc Python (escape mangling). Check `git diff -w --stat` equals `git diff --stat` before committing a file with mixed line endings.
