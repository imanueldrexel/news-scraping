# QA decisions — index

## Cross-cutting principles
- Repo workflow (CLAUDE.md): dev implements and labels `status: ready-for-qa`; only QA closes or sends back. QA files every ticket that comes from testing.
- Verify independently of dev's evidence: suites, own mutants (`PYTHONDONTWRITEBYTECODE=1`), read-only live checks, scheduled-run evidence.
- No production DB writes without asking the owner.
- One ticket per finding; never park findings as comments on umbrella tickets.

## Active features
- [qa-pass-2026-10-04](qa-pass-2026-10-04.md) — verify the 9 ready-for-qa tickets (spec: `.10x/specs/2026-10-04-qa-verification-pass-design.md`)
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) � audit of OPS-20/SYS-68/SYS-67/SYS-63: nothing closed; SYS-71 P2 blocks, 3 P3s filed (2026-10-04)
- [qa-pass-2026-10-04-night](qa-pass-2026-10-04-night.md) - P1/P2 verified against the tickets' wording; 17 closed, 5 held for runs, 7 filed; mutation runs in clean copies
- [newsletter-5min-edition](newsletter-5min-edition.md) - tracker #244: 4 closed (SYS-81/84/85, OPS-41), SYS-80 sent back, 4 held (owner / scheduled runs), 8 filed (SYS-86..89, OPS-44, DBT-56..58); QA's own test set + 57 mutants (49 killed) in `scripts/experiments/qa_newsletter_244/` (2026-10-05)
- [qa-pass-2026-10-06-night](qa-pass-2026-10-06-night.md) - P3 burn-down + #244 fixes: 12 closed, SRC-58 held for the 07:00 crawl, 4 filed (SRC-59 P2, SYS-91, DBT-60, OPS-46); 84/84 mutants killed

## Cross-cutting lessons
- A heuristic validated only on the days it was tuned on is unvalidated: measure it on every pair and on untuned days (SYS-86).
- An LLM-dependent Done-when ("the re-render shows no X") can pass on one replay and fail on the next (SYS-80 v4 vs v5): re-check it on the latest output, and prefer a scripted, repeatable measure.
- Mutation runs: print the unmutated baseline and each kill's failing test; a worktree reaching the venv through a junction in the scratchpad "kills" everything at collection (MAX_PATH).
- A repair of a derived value must cover every store that holds a copy (SYS-90: articles fixed, FAISS metadata not -> SYS-91); and a mutant that survives a narrowed test group is not equivalent until it survives the full `tests/unit`.
