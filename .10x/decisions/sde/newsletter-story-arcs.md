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

---

# 2026-10-14 (morning): arcs read as stories -- SYS-154..160 (QA's tickets from the owner's read)

## Built
| Ticket | What | Commit(s) |
|---|---|---|
| SYS-160 #355 | `core/arc_style.py`: date-led, opens-on-date, repeated opening, non-events, tie to today, defined once. `replay_story_arcs.py`: `style_metrics`, `reads_as_story` rows, `--compare` (3-way blind A/B/C), `--metrics-from` (baseline on an old run) | fec04c3 |
| SYS-154 #349 | latar rules (1)-(6); "setiap fakta bertanggal" gone; each LINI MASA item shows its relative phrase (`relative_name`); "Senin (12/10)" for hari_ini only; latar asks 60 / accepts 70 (`ASKED` vs `LIMITS`) | fec04c3, 841992e, 702386c |
| SYS-155 #350 | worked example rebuilt from 2026-10-02's real KONTAN articles, as a story (frame, 0 dates) | fec04c3 |
| SYS-156 #351 | `style` refusal (`chronicle`): > 2 dates, > 1 sentence *opening* on a date, same opening word; the detail quotes the sentences; a length refusal carries style too and names the cut | fec04c3, 841992e, dcca96a, 702386c |
| SYS-157 #352 | `source_check.relative_times` (table) + `unbacked_times`; "… sebelumnya" not read | fec04c3, dcca96a |
| SYS-158 #353 | `source_check.ordinal_claims` + `overcounted`; records ("terendah/tertinggi sejak") need a source | fec04c3, 702386c |
| SYS-159 #354 | `tied_to_today`: not opening on a date + a shared content word (names included) up to affixes (`stems`) | fec04c3, 1e56720 |

## Deviations (each on its ticket)
- **SYS-159 is not "event word only".** That rule refused the research file's own rewrite and passed the recap (EXPERIMENTS 2026-10-14 SYS-160 entry). Exact overlap also refused "Kesepakatan ini …" against today's "menyepakati", hence the word families.
- **SYS-156's style problems go into the same retry detail as numbers/dates (and length), named first;** it is not a separate early raise. Rule 2 counts sentences that *open* on a date; the metric counts sentences that *carry* "pada <date>".
- **SYS-158 also covers "terendah/tertinggi sejak".**
- **SYS-157 adds "<Hari> lalu" and "… bulan ini/lalu",** and `relative_name` for the prompt.

## Evidence
- Replays (EXPERIMENTS "re-runs of the arc replay"):
  - v2 4/8;
  - v3 7/8;
  - v4 17/20;
  - **v5 (702386c) 18/20 accepted, date-led 7.8%, 0 latar ≥ 3 dates, tied 17/17**;
  - $1.68 at peak in all.
- Owner files: `digests/preview/arcs-v5/` (untracked).
- Unit 3,243 passed.
- 55 mutants (sys148/154..160) KILLED in a scratch worktree, torn down junction-first; venv intact.

## Left / tech debt
- **The owner's 3-way re-read and the 5-day blind A/B** (SYS-154/SYS-150 gate). `NEWSLETTER_ARCS` stays 0.
- **Polri arc slip:** "Kini … bertambah menjadi 199 orang" reads a wave's count as a running total. No check catches it; it is for QA's hand-check. It could become a cumulative-claim guard if QA tickets it.
- **Accepted share sits at the 90% gate.** Both fallbacks are market stories with a number the model made up. A price story with a timeline is the weak spot.
- The stems are a heuristic (one prefix, one suffix, stems ≥ 4 letters), used only for the tie. Not a stemmer: do not reuse it for search.

---

# 2026-10-15 (early morning): QA rework of the arc guards -- SYS-157/158 (sent back), SYS-161..164, DBT-77

Design: `.10x/decisions/architect/newsletter-story-arcs.md`, section "2026-10-15". No new ADR (inside ADR-017's seam).

## Built (3e8b90c code + tests, 89eb879 registry + EXPERIMENTS)
| Ticket | What | State |
|---|---|---|
| SYS-157 #352 | count-ago phrases with their own span; vague counts matched, unread; `relative_phrases` | ready-for-qa |
| SYS-162 #357 | `unbacked_times` reads only today's terkait text (`stated_today`) | ready-for-qa |
| SYS-158 #353 | whole-time record keys + `stated_claims` (year may drop, not change); "N kali berturut-turut"; verb/"belah" collectives | ready-for-qa |
| SYS-161 #356 | `unbacked_changes` + prompt rule 3; calibrated on DB text | **in progress**: the 10-11 LLM re-run is held for the SumoPod top-up |
| SYS-163 #358 | `agenda_repeats` -> dropped, not refused | ready-for-qa |
| SYS-164 #359 | `time_anchors`, `opens_on_time`, `time_led`; MAX_LATAR_ANCHORS = 3; openings cap on time; new opening shapes; metrics | ready-for-qa |
| DBT-77 #360 | 2-date back-story in the metric test; `qa_metric_ge2_dates` registered | ready-for-qa |

## Deviations / judgement calls (each on its ticket)
- SYS-163: dropped rather than refused (no reader gain from a retry).
- SYS-164: `opens_on_date` keeps its name and calendar-only meaning (QA's tests call it); `opens_on_time` is new.
  The openings cap now counts relative-time openings too ("the caps" in the handoff).
- SYS-161: applied to every prose field, not only latar/hari_ini, like the other number checks.
- QA's `test_a_collective_after_a_verb_does_not_cost_a_retry` stays red on its own fixture (`subject`: article [1]
  names neither "Istana" nor "Negara"); the SYS-158 part of it is fixed. Explained on #353 for QA's call.

## Evidence
- Unit 3,320 passed (5 skipped). QA's `test_qa_arcs_story.py` 83/84 (the fixture case above).
- Mutants: 76/76 arc mutants KILLED in a scratch copy of the working tree (`%TEMP%\...\scratchpad\mut`, plain copy,
  no worktree/junction); 31 new, 5 retargeted. QA's `qa_mutants_1014.py`: every matching mutant KILLED; 4 no longer
  match (named on #352/#359 with their registry equivalents).
- v5 metrics (SYS-164 definition): time-led 11/51, >= 3 anchors 1/17; QA's 8/51 and 3/17 reproduce under QA's
  definition (frames counted, fewer opening shapes).
- Offline: 2 of the 17 accepted v5 arcs (Karhutla 10-11, Lobster 10-12) would now be refused on the first try.

## Ops done in passing
- `.env`: `KNOWLEDGE_DAILY_COST_LIMIT_USD` 8 -> 1.5 (owner decision recorded for 2026-10-15). Spend since the 10-12
  top-up is $20.25 logged + ~$1.68 of unlogged replays: the balance is about $0-2.

## Left
- SYS-161's 10-11 re-run (~$0.15) after the owner's top-up; then ready-for-qa. The same run shows whether the
  retry repairs Karhutla/Lobster under SYS-164 (the accepted share sits at the 90% gate).
- `.env` is not in git: the cap change is recorded here and in memory only.

## 2026-10-15 (morning): SYS-161's 10-11 re-run, and the bare-"total" hole
- The owner okayed the run (SumoPod ~$3). `arcs-v6`: $0.1064, 4 arcs, 0 refusals. The Polri story was not picked as a top story, so the replay can't show its arc.
- Offline against all 24 stored Polri articles, the v5 claim passed: two say "Total ada 199 ... yang dirotasi", which is the size of that one telegram. Fix: `_TOTAL_OR_CHANGE` no longer counts bare `total|totalnya|keseluruhan`. Change verbs, `kumulatif|akumulasi`, a running period and "dari N" still count. Prompt rule 3 now says "total ada N" alone is only that event's count.
- Tests: `TestUnbackedChanges::test_a_bare_total_is_the_size_of_one_event`; "Total ada 12 kasus" in the passing list became "Secara kumulatif ada 12 kasus". Mutant `sys161_bare_total_is_a_total` added and the `sys161_source_change_verb_ignored` pattern retargeted. All 6 `sys161_*` are KILLED.
- Accepted cost: a source that says only "total N" for a real running sum now costs one retry. The model then tells N as today's event. The reader loses nothing.
- v6 ran on the old prompt. It was not re-run, to save the balance.
