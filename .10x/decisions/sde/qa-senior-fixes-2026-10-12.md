# SDE: QA + senior list, 2026-10-12

Spec: `.10x/specs/2026-10-12-qa-senior-fixes-design.md`. ADR-010/011/012. Owner decisions (as CTO/PM) are in `decisions/cto/qa-senior-fixes-2026-10-12.md`, plus three made mid-build (below).

## Built (each ticket `status: ready-for-qa` with evidence, unless noted)

| Ticket | Commit(s) | What | Mutants (KILLED) |
|---|---|---|---|
| SYS-111 #287 | 2ffdf28 | `--until` resolved once at the top of `repair_boilerplate_bodies._apply_locked`; a malformed value fails before anything runs | `sys111_resolved_twice` |
| SYS-139 #320 | 84781b2 | Soft deadline (ADR-011): `SourceWorker(soft_margin_s)` → job budget → monotonic deadline → `crawl_newsdetails(deadline=)`. No batch starts unless the slowest batch so far fits. Unreached rows untouched and out of OPS-16's ratio. Flush, then `completed` with a note. `SCHEDULE_SOFT_DEADLINE_MARGIN_S=180` | 7 `sys139_*` |
| SYS-104 #274 + SYS-140 #322 | f842ae7 | ADR-010: `web/followup.py` (prompt, check, deterministic fallback); `QueryProcessor.resolve` (cap, accounting, log); `terms(question, *more)`; `_keyword_query(question, *more)`; `OpenAICompatSummarizer(max_retries=)` | 25 (14 new, 10 earlier `sys104_*` incl. 2 retargeted, `qa1012_thread_three` retargeted) |
| SYS-141 #323 | e12e8e9 | `similarity()` reads `vs_l2` once; `_l2_positions(vs)`; docstring `1 - d/2` | `sys141_reads_vs_l2_twice` |
| DBT-66 #319 | 4392b9f | 4 threshold tests with absolute values | QA's 4 `qa1012_*` (full suite) |
| DBT-65 #318 | 4392b9f | EXPERIMENTS.md `<wt>\venv`; hygiene test for C0 control characters in `*.md` | `dbt65_vertical_tab_back` |
| SYS-137 #316 | 8b224ec, 7c1fdef | Store check `l2_over_max_tokens`; `drop_oversized_queued_chunks.py`; **production write done** | 2 unit + 4 integration (manual, test DB) |
| SYS-138 #317 | 62296a2 | ADR-012: soft 7-day window for the week cue | 4 `sys138_*` |
| SYS-112 #289 | — | Measured, **not fixed** (owner): its causes are not recency. Evidence on the ticket; not ready-for-qa | — |
| SYS-142 #324 | — | Measured: 45,741 tails = 5.5% of served L2. The even-window fix is proposed; **owner to decide when**. Not ready-for-qa | — |
| DBT-67 #325 | — | **Not started**: blocked on QA closing SYS-111 (senior's order) | — |

## Mid-build owner decisions
1. SYS-104: the recency cue comes from the rewrite on the LLM path (QA wrote "own words only"); the fallback uses own words only.
2. SYS-137: guard = store check only (a crawl-path replace would need a content-aware SYS-17 reuse to be kill-safe).
3. SYS-138/112: ship the week window only; the relative gate and a "sekarang" window were measured and rejected.

## Deviations from the plan
- **SYS-137 dropped both chunk levels, not L2 only (spec said L1 untouched).** The first production run kept L1 and the store check read `l1_not_in_l2` 2,171. A queued sitemap has no article and no mentions, and its June L1 came from June's extraction. Fixed in 7c1fdef and re-applied.
- The SYS-137 re-chunk's deferred block re-embedded VIVA's 4,198 SYS-139 rows without vectors (`embedding_id IS NULL` → 0). Told QA on SYS-139 so it is not mistaken for a completed VIVA run.
- `_keyword_query` takes varargs, not a sequence: a `str` is a `Sequence[str]` and was being split into characters.

## Measurements (EXPERIMENTS.md 2026-10-12)
- SYS-104 rewrite: switch 22/25 = alone; elliptical 35/35 (alone 16/35); held-out 25/30; 0.9-2.9 s; $0.0017 for 18 calls.
- SYS-138: KPK week cards 0/5 → 5/5, IHSG 3/5 → 5/5, 0 regressions on 15 questions.
- SYS-142: 45,741 overlap tails (17,034 with ≤ 5 new words).
- SYS-137: 11,281 oversized L2 rows → 0; 612 articles re-chunked.

## Traps hit
- The scratchpad worktree path exceeds 260 chars through the venv junction, so the baseline errors and every mutant reads KILLED. Use `%TEMP%\mutwt` (trap line added).
- Bash heredocs in this harness mangle `\\n` / `\\v` (they wrote a vertical tab and broke a runner string literal). Write edit scripts to the scratchpad and run them, and `ast.parse` the runner after editing it.
- Git Bash `date` printed LOCAL time here; read the clock with `Get-Date` (index note fixed).

## Tech debt created
- `drop_oversized_queued_chunks.py` is a third script importing `repair_boilerplate_bodies`' helpers (`_crawl_running`, `_faiss_dirs`, `backup`, `delete_vectors`): DBT-67 must include it.
- QA's `probe_topic_switch_followups.py` now makes rewrite calls with `usage=None`, which logs one warning per call.
