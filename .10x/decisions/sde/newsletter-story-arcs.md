# Newsletter story arcs: what was built (SDE, 2026-10-13 night)

Tracker #336 · ADR-016, ADR-017 · design: `decisions/architect/newsletter-story-arcs.md` · order: `decisions/engineering-manager/newsletter-story-arcs.md`.

## Built, in the planned order
| Step | Ticket | Commit(s) | State |
|---|---|---|---|
| 1 | DBT-72 #344 `core/source_check.py` (+ SYS-153 #343 fixed) | 223352b | ready-for-qa |
| 2 | DBT-73 #345 `core/llm_json.ask_json` | 130c1e3, f929ded | ready-for-qa |
| 3 | SYS-147 #337 `core/thread_finder.py`, `faiss/l1_search.py`, `get_timeline_rows` | d56551c | ready-for-qa |
| 3 | DBT-74 #346 `application/newsletter_app.py` (own composition root) | d56551c | progress comment; needs old-path comparison + 10-14 12:00 log |
| 4 | SYS-148 #338 `core/story_arc.py` | a26a6a5 (+ test commit) | progress; needs SYS-150's ≥ 90% accepted |
| 5 | DBT-75 #347 `plan()` / `build_edition()` / `generate(digests_dir=)` + traces | 0c4b8b6 | ready-for-qa |
| 6 | SYS-149 #339 `EditorPolicy` + arc stage behind `NEWSLETTER_ARCS` | c1a8269 (+ test commit) | ready-for-qa (owner: confirm ≥ 1 non-finance) |
| 7 | SYS-150 #340 `scripts/experiments/replay_story_arcs.py` | 2dae824 | replay run; owner's blind read pending |

## Deviations from the plan
- **DBT-72:** no `SourceText` class; callers still pass strings. `unsupported_number` gained a `dates` argument and `without_dates()`, so SYS-148 can license a timeline item's own date without licensing its digits as numbers.
- **DBT-73:** `check(answer, attempt)` takes the raw answer, not a dict (`parse`/`parse_editor` keep their signatures). `Outcome` also carries `refusals` (Rejected objects) for DBT-75's trace. The editor's unparseable-answer detail is now "jawaban bukan JSON".
- **SYS-148:**
  - the thread check is "≥ 1 shared *event* word" (content words that are not names), not "≥ 2 shared content words". The latter flagged the genuine "209 Ha Lahan Masih Terbakar" item and passed "Prabowo Lantik Wantimpres" only by luck. This is the echo guard's own name/event split (SYS-86);
  - numbers and dates are named apart in one refusal.
- **DBT-75:**
  - the typed `Story` moved to DBT-76 #348 (EM call, see the EM file);
  - "reproduce a stored replay's metrics" was replaced by an 8-fixture-day byte-identical comparison (the model is not deterministic).
- **SYS-149:**
  - over budget, the 4th story is moved to Sekilas by mutating `choice` in place (`render`);
  - with arcs on and no summarizer, every top story is its summary as prose;
  - with arcs on and no NEWS_L1 search, every story is told as new (logged).

## Evidence (all zero-cost unless said)
- DBT-72: 0 of 1,006 stored accepted summaries newly refused (after the "M2 Agustus" fix).
- DBT-73: 710/710 stored summary calls replayed identically, old vs new `summarize_story`.
- DBT-75 + SYS-149 (arcs off): old vs new generator and edition on 8 fixture days → digest, edition and row byte-identical; the editor prompt under `POLICY_TODAY` is byte-identical (1,977 chars).
- SYS-147: live read-only timelines on 2026-10-12's leads (karhutla 09-23/24, Houthi 10-06 and 09-20).
- DBT-74: new setup 11.5 s / 1.21 GB after the build / 1.67 GB peak.
- SYS-150 smoke on 2026-10-12 (LLM, $0.13 at the peak price): arcs 4/4 built, 811 words (today 919), 10 timeline items, 1 new story.
- **Tests:** unit 3,090+; integration 225 passed / 1 skipped. Mutants: every `dbt72_*`, `dbt73_*`, `sys147_*`, `dbt74_*`, `sys148_*`, `dbt75_*`, `sys149_*` KILLED, plus the retargeted SYS-80/82/83/87 ones. Two equivalents were removed with dead code; four survivors were turned into tests.

## Incident
`test_scheduled_newsletter.py` patched only `init_crawler`, so one run built the real `build_newsletter_service()` against a mocked DB and overwrote `digests/2026-10-03.md` (gitignored) with an empty-day page.
- **Restored** from `digests/preview/before-2026-10-04-qa/2026-10-03.md` (2,052 articles, 94/94 summaries). That copy says "Dihasilkan 10:18 WIB" while the DB row's `generated_at` is 08:58, so it may not be the last production write.
- **The damaged file** is in the session scratchpad.
- **Prevention:** the tests now patch `build_newsletter_service` and make `init_crawler` raise.

## Tech debt created / left
- DBT-76 #348: the typed `Story`.
- `cluster["related"]` is a new dict key (SYS-149's centroid), documented at `_apply_story`.
- QA's own `qa_newsletter_244/qa_mutants_244.py::ss_retry_without_reason` targets the pre-DBT-73 loop (QA's file, left alone).
- 24 pre-existing registry mutants elsewhere (crawl, ops, RAG) no longer match their files (`sys104_*`, `sys138_*`, `ops32_*`, …). This was not caused by this work.

## Production state
- `NEWSLETTER_ARCS` defaults to 0, and a test fails if that default flips. The 2026-10-14 12:00 run is today's edition, byte for byte, built through DBT-74's composition root (its log should show no NEWS_L2 or e5-large load).
- No migration and no production DB write. The replays wrote only under `digests/preview/arcs*`.
