# SDE: QA + senior list, 2026-10-12

Spec: `.10x/specs/2026-10-12-qa-senior-fixes-design.md`. ADR-010/011/012.

## Built (ready-for-qa, evidence on each ticket)

| Ticket | Commit | What | Mutants |
|---|---|---|---|
| SYS-111 #287 | 2ffdf28 | `--until` resolved once at the top of `repair_boilerplate_bodies._apply_locked`; a malformed value fails before anything runs | `sys111_resolved_twice` KILLED |
| SYS-139 #320 | 84781b2 | Soft deadline (ADR-011): `SourceWorker(soft_margin_s)` → job budget → monotonic deadline → `crawl_newsdetails(deadline=)`. No batch starts unless the slowest batch so far still fits; unreached rows untouched and out of OPS-16's ratio; flush + `completed` with a note. `SCHEDULE_SOFT_DEADLINE_MARGIN_S=180` | 7 `sys139_*` KILLED |
| SYS-104 #274 + SYS-140 #322 | f842ae7 | ADR-010: `web/followup.py` (prompt, check, deterministic fallback), `QueryProcessor.resolve` (cap, accounting, log), `terms(question, *more)`, `_keyword_query(question, *more)`, `OpenAICompatSummarizer(max_retries=)` | 25 KILLED (14 new, 10 earlier `sys104_*` incl. 2 retargeted, `qa1012_thread_three` retargeted) |

## Deviations from the plan
- **SYS-104 recency cue:** QA's wording said "own words only". The owner approved taking it from the rewrite on the LLM path; the fallback uses own words only.
- `_keyword_query` takes varargs, not a sequence: a `str` is a `Sequence[str]` and was being split into characters.

## Measurements
- SYS-104 on production (read-only): switch 22/25 = alone; elliptical 35/35 (alone 16/35); held-out 25/30 (alone 20/30); 0.9-2.9 s; $0.0017 for 18 calls (EXPERIMENTS.md 2026-10-12).

## Traps hit
- **The scratchpad worktree path exceeds 260 chars through the venv junction**, so the baseline errors and every mutant reads KILLED. Use `%TEMP%\mutwt` (trap line added).
- **Bash heredocs with certain contents fail in this harness** ("unexpected EOF while looking for matching `''"). Write edit scripts to the scratchpad and run them.

## Tech debt created
- None new. `probe_topic_switch_followups.py` (QA's) now makes rewrite calls with `usage=None`, so each call logs a warning; harmless.
