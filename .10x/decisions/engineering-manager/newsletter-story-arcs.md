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
