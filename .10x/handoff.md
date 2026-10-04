# Current Handoff

## From: SDE -> To: QA (and the owner for the decisions below)
**Date:** 2026-10-04 (evening)
**Phase:** Implementation -> QA
**Feature files:** `decisions/sde/newsletter-digest-quality.md`, `decisions/sde/sys-39-knowledge-extraction.md`, `decisions/sde/body-cleaner-and-repair.md`; ADR-003.

### Ready for QA (label `status: ready-for-qa`, evidence on each ticket)
- DBT-50 #214: recount test uses the script's own `DRIFT_SQL`; mutants = drop each of the 3 OR clauses.
- SYS-69 #217: one link per outlet, headline labels (`tests/unit/test_newsletter_links.py`). Offline only; a regenerated digest needs the owner-approved newsletter run.
- SYS-65 #211: cross-section merge; the replay is `scripts/experiments/replay_cross_section_merge.py --date 2026-09-28` (read-only, expect 2 pairs before / 0 after).
- SYS-75 #225: the body cleaner removes the widget, not the paragraph (`clean_line`). Check: `repair_boilerplate_bodies.py` "longest removed lines" holds no sentence; known residual ~7 glued-headline articles.

### Built, NOT labelled (needs the owner)
- OPS-38 #212: date arg + `scripts/run_scheduled_newsletter.py`; decide 06:30 vs 12:00 and approve registering "NewsAggregator Newsletter".
- SYS-39 #125 / OPS-20 #136: provider, cost and peak guards, bake-off. Decide how to settle the 0.85 gate, approve applying `scripts/migrate_api_usage_tokens.sql` to `newsaggregator` (backup first), then set `KNOWLEDGE_LLM_PROVIDER=openai` and schedule.
- SYS-73 #223: dry run only; approve the report, a backup, and one-job-vs-per-source before the apply path is written.

### What to test / mutate
`PYTHONDONTWRITEBYTECODE=1 venv\Scripts\python.exe scripts\experiments\qa_mutation_runner.py` has `sys65_*`, `sys69_*`, `ops38_*`, `sys39_*`, `sys75_*` mutants (run on a clean tree). Unit 1,976 / integration 165 pass. Things worth a second look: the extractor's new loop (`seen` set, five stop conditions), `KNOWLEDGE_BATCH_SIZE` meaning, the Gemini daily-quota classification, and any DETIK body that still shows `Tautan telah disalin`.

### Risks
- Running `task=extract_knowledge` or `task=newsletter` on production before the migration fails the extractor's usage insert.
- `task=newsletter` with no date now digests YESTERDAY.

### Not done
SYS-74 #224, SYS-41 #127, SRC-34 #124, SRC-47 #157, SRC-42 #145, SRC-40 #134, SRC-39 #133, DBT-19 #69, DBT-22 #73, DBT-01 #20; SRC-56/SRC-03 are owner-only.

---

## Handoff History
- 2026-10-04 PM -> SDE: SYS-39 (extract all news on DeepSeek, peak guard). Picked up and built (see above).

- 2026-10-04 SDE -> QA (still pending QA): SYS-71 #219, SYS-72 #220, DBT-51 #221, DBT-52 #222 ready-for-qa, #216/#215/#204 re-labelled; #204 needs the 19:00 crawl; stray partial-day 2026-10-04 digest row awaits the owner. Full text: `decisions/sde/p1-p2-newsletter-fixes.md`, section "QA feedback fixed".
- 2026-10-04 QA -> SDE: fix SYS-71 first, then SYS-72, DBT-51, DBT-52; owner approved task=newsletter, SYS-67 as scoped, SYS-63 repair after SYS-72.

- 2026-10-04 planning -> SDE: P1/P2 fixes + newsletter (spec + ADR-001, ADR-002).
- 2026-10-04 brainstorming -> QA: verification of 9 ready-for-qa tickets (baseline done, see decisions/qa). QA pass is paused while dev work runs; scheduled-run evidence still pending.
- 2026-10-04 init-project -> first active role: state initialized.
