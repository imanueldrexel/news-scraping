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
- [rag-search-redesign](rag-search-redesign.md) — dev-side verification of tracker #272; gaps for independent QA
- [qa-pass-2026-10-07-rag](qa-pass-2026-10-07-rag.md) - independent QA of #272 + SYS-103: 13 closed (incl. SRC-58), 8 filed (SYS-104..108, SRC-60/61, DBT-61) + test gaps; keyword-only hits never reach the top 5
- Lesson: a retriever's candidate count is not its contribution; count the top-5 cards by origin (`probe_rag_rank_breakdown.py`).
- [qa-pass-2026-10-12](qa-pass-2026-10-12.md) - SDE's 10-08/09 handoff + held tickets: 24 closed, SYS-104/SYS-111 sent back, 4 filed (SYS-137/138, DBT-65/66); topic-switch follow-ups regressed
- Lesson: a fix that adds context to a query must be probed on inputs that never needed it (SYS-104); a 'KILLED rc=4' is a broken test list.
- Lesson: run the unmutated baseline in every mutation copy; identical failure counts across different mutants mean an environment failure, not kills.
- [qa-pass-2026-10-12b](qa-pass-2026-10-12b.md) - dev's fixes of the 10-12 list: 8 closed (SYS-111/104/140/141/137, DBT-65/66, OPS-49), SYS-138 sent back (off-topic card 1 on thin weeks), SYS-139 held for 3 VIVA runs, 5 P3s filed (SYS-143..145, DBT-68/69)
- [qa-pass-2026-10-13](qa-pass-2026-10-13.md) - audit of the dev's fixes: 6 closed (SYS-138/143/91, DBT-67/68/69), SYS-144/145 + DBT-60 sent back (held-out -nya adverbs regress kept topic switches on the served path; Decimal/numpy dates), SRC-59/SYS-139 held, filed SYS-146, DBT-70/71, SRC-62
- Lesson: measure a ranking rule on held-out questions; the RAG floor is a tail filter, not a lead filter. Probe an LLM step's fallback on the same pairs.
- [newsletter-story-arcs](newsletter-story-arcs.md) — 2026-10-14: the arcs pass the automatic gates but read as a chronicle (69% date-led latar); SYS-154..160 filed; SYS-157/158 release-blocking with SYS-154
