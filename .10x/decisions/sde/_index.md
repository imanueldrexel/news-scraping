# sde decisions — index

## Active features
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) — OPS-20/SYS-68/SYS-67/SYS-63 built; QA feedback SYS-71/72, DBT-51/52 fixed 2026-10-04; ready-for-qa

- [newsletter-digest-quality](newsletter-digest-quality.md) — SYS-69, SYS-65 ready-for-qa; OPS-38 code done, job not registered (owner)
- [sys-39-knowledge-extraction](sys-39-knowledge-extraction.md) — provider/cost/peak guards built (ADR-003); 0.85 gate and prod migration need the owner; not closed
- [body-cleaner-and-repair](body-cleaner-and-repair.md) — SYS-75 fixed (ready-for-qa); SYS-73 dry run done, apply path waits for the owner; DBT-50 ready-for-qa

- [newsletter-5min-edition](newsletter-5min-edition.md) — tracker #244: SYS-80..85, OPS-41..43 built 2026-10-05 (structured summaries + guards, editor pass, copy module, phone PDF, Telegram message); replayed on 3 days; SYS-82/SYS-83 targets partly missed, owner decisions listed. QA's findings fixed the same night (SYS-86/80/87/88, OPS-44, DBT-56..59); SYS-88's backfill awaits the owner

## Cross-cutting SDE notes
- PowerShell does not pipe a here-string into `git commit -F -`; write the message to a scratch file and pass its path.
- A replay that spawns one process per date imports the code at each start: never edit source between dates (it mixes versions), and never run `qa_mutation_runner.py` at the same time (it mutates files in place).
- PyMuPDF is in `py -3.11` (not the venv): `scratchpad/contact.py`-style contact sheets are the quick way to look at a whole PDF.
- Edit regexes in `core/utils/utils.py` with the Edit tool, not heredoc Python (escape mangling). Check `git diff -w --stat` equals `git diff --stat` before committing a file with mixed line endings.
- The harness turns backslash escapes inside python heredoc strings into control characters (a lone CR once made git treat OPERATIONS.md as binary). Use Edit/Write for text with backslashes and scan for lone CR afterwards. Never rewrite a whole file's line endings; replace per region (LF first, then CRLF).
- Wait on background work with a Monitor `until grep ...` loop; do not edit tracked files while `qa_mutation_runner.py` runs (it restores by `git checkout`).
- Mutants in a worktree without the MAX_PATH trap: `subst M: <scratchpad>`, `git worktree add <scratchpad>\mutwt HEAD`, `mklink /J M:\mutwt\venv <repo>\venv`, run from `M:\mutwt`. A narrowed `QA_MUTANT_TESTS` set reports false survivors for code guarded elsewhere (OPS-40's in `test_notify_telegram.py`): re-run every survivor on the full `tests/unit` before calling it a gap.
- Replays spend the production SumoPod account (prepaid balance, shared with the 21:00 extraction and the 12:00 newsletter). Check the balance before a replay round, and never run one while the extraction is running.
- A module constant used as a default argument (`pick_articles(limit=MAX_ARTICLES)`) cannot be monkeypatched by name: patch `__defaults__` (DBT-59).
