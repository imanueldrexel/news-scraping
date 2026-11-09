# Newsletter story arcs: delivery plan (EM, 2026-10-13)

Tracker #336 · ADR-016, ADR-017 · re-prioritised after the `/deepen` review (owner: "make the prioritisation based on your suggestion").

## Sequence
| Step | Ticket | Depends on | Size (dev sessions) | Gate to the next step |
|---|---|---|---|---|
| 1 | DBT-72 #344 source_check (fixes SYS-153 #343) | n/a | 0.5-1 | guard tests + mutants green; replay ±2 pts |
| 2 | DBT-73 #345 ask_json | DBT-72 (shared `Rejected`) | 0.5 | summary/editor byte-identical |
| 3 | SYS-147 #337 thread finder + DBT-74 #346 newsletter-only setup | n/a (parallel to 1-2) | 1 | live read-only check through the new setup; RSS measured |
| 4 | SYS-148 #338 arc writer | 1, 2 | 1 | unit + mutants; no local guard/loop |
| 5 | DBT-75 #347 plan/build + Story | 2 | 1 | byte-identical digest/edition; replay without patching |
| 6 | SYS-149 #339 edition stage + EditorPolicy | 3, 4, 5 | 1 | `NEWSLETTER_ARCS=0` byte-identical |
| 7 | SYS-150 #340 replay + blind A/B + PDF check | 6 | 0.5 + owner reading | **ship gate**: arcs win ≥ 4/5 |
| P1 | SYS-151 #341, SYS-152 #342 | 7's numbers | 1 each | per their Done-when |

Total P0: about 6-7 dev sessions (was ~3 before the re-scope). The ~3-4 added sessions are the price of ADR-017.

## Parallelism
Steps 1-2 and step 3 touch disjoint files (core guards vs datasource/composition), so two sessions could run them side by side. Everything from step 4 on is sequential.

## Process rules (project)
- Dev labels each ticket `status: ready-for-qa` with Done-when evidence and never closes it. QA closes.
- Commit footers use `Refs #N`.
- Every experiment (replays, RSS measurement) goes in EXPERIMENTS.md the same session.
- No production DB write in this tracker. `NEWSLETTER_ARCS=1` in `.env` is the owner's step after SYS-150.

## Risks
- **A "pure move" hides a behaviour change:** byte-identical/±2 gates on every DBT ticket.
- **The memory-heavy test runs on this host collide with the 07:00/19:00 crawl and the 21:00 extraction:** run mutants outside those windows (see the 2026-10-12 notes).
- **Owner time for 5 blind pairs:** schedule it when SYS-150 is ready.

## EM call during the build (2026-10-13, ~23:20)
- **The typed `Story` moved out of DBT-75 into DBT-76 #348.** It touches ~30 code sites, 11 test fixtures and QA's own `scripts/experiments/qa_*` harnesses. The arcs do not need it to be correct. Every commit tonight is also the code the 2026-10-14 12:00 run uses, so the widest diff was the wrong one to land before a live run. DBT-75 kept everything the arcs and SYS-150 need: plan/build/generate, the traces, no patching.
- **SYS-150's replay spends LLM money.** Smoke run 1 date: $0.13 at the peak price; full run 5 dates: ~$0.66 at the peak price, less off-peak. The prepaid balance is tight until the ~10-16 top-up (status 2026-10-12). One-off and within the ~$100 budget (CTO llm-budget), so it went ahead; the measured cost goes on the ticket.

## 2026-10-18: QA's 10-18 queue, plan (13 tickets)
- **Timing.** The 12:00 edition job imports the working tree. No production code is edited until it has loaded
  (check `crawl_log` / the edition file). After that each ticket lands as its own commit, with the suites green,
  before the next starts. Nothing half-done is left in the tree.
- **Order (QA's, by severity):**
  1. causal: SYS-188 + SYS-181 together (`_covers`, `root`), then SYS-181's anaphor;
  2. SYS-189;
  3. SYS-185 + SYS-192;
  4. SYS-183 + SYS-187;
  5. time: SYS-186 send-back + SYS-191 + SYS-193;
  6. SYS-177;
  7. SYS-190;
  8. DBT-83.
- **Per ticket:** QA's red tests green, the controls green, a unit test per rule in tests/unit, one registry mutant
  per rule KILLED in a copy, and `recheck_causes.py` (causal) or the replay time recheck (time) before and after.
- **Budget.** No LLM spend; every recheck is offline over the stored replays.
- **Risk.** The owner's "every word" rule lowers the backed count on purpose. Report it; do not tune it back.
