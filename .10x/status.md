# Project Status

## Project: NewsAggregator
**Current Phase:** Implementation (dev): P1/P2 fixes + newsletter. Design approved by owner choice of DeepSeek; spec + ADR-001 written.
**Last Updated:** 2026-10-05 (night) by sde
**Health:** On Track

## Progress

### Done
- Project state initialized (`.10x/`).
- Brainstorm: owner chose "close out the open QA/ops queue" with a QA verification pass first; design approved; spec at `.10x/specs/2026-10-04-qa-verification-pass-design.md`.

### In Progress
- QA: baseline done (unit 1,643 / integration 156 / 140 mutants, 0 survivors). Per-ticket checks next; scheduled-run evidence waits for the 07:00 crawl.

### QA audit 2026-10-04 (dev commits 74d2ca5..826730c)
- Unit 1,789 pass; 10/11 QA mutants killed. Nothing closed (no ready-for-qa handoff yet). Blocking: SYS-71 #219 (P2). Also SYS-72 #220, DBT-51 #221, DBT-52 #222 (P3). Report: reviews/2026-10-04-qa-report.md

### Pending
- Per-ticket verdicts (close / send back / stay ready-for-qa)
- `HANDOFF_2026-10-04.md` for dev
- Dev burn-down afterwards: OPS-20 (P1), OPS-38/SYS-68/SYS-67/SYS-65/SYS-69, SYS-63, P3s

### Blocked
- SRC-56 TEMPO: owner browser test (fingerprint block), source paused.
- OPS-36: owner must register the liveness job and approve the drill.

## Risks
- 2026-10-04 07:00 crawl is the first run of the bot UA, host pacing and retry changes across the fleet.
- Gemini free tier is 20 requests/day (OPS-20); gates extraction, audit and newsletter.

## Dev plan 2026-10-04 (spec: specs/2026-10-04-p1-p2-newsletter-fixes-design.md, ADR-001)
- [ ] OPS-20 #136 + SYS-68 #216 summarizer, accounting, docs
- [ ] Newsletter result for owner (needs DB-write approval)
- [ ] SYS-67 #215 clustering (measure, then fix)
- [ ] SYS-63 #204 boilerplate cleaner
- Not code: SRC-56 #205, SRC-03 #14

## SDE update 2026-10-04 (after QA feedback)
- [x] SYS-71 #219 (P2), SYS-72 #220, DBT-51 #221, DBT-52 #222 fixed and labelled `status: ready-for-qa`; #216, #215, #204 re-labelled with evidence (#204 waits for the 19:00 run).
- [x] Newsletter run for 2026-10-03: 94/94 summaries (a partial 2026-10-04 row was also written by mistake, see decisions/sde).
- [ ] SYS-73 #223 dry run (unblocked); OPS-38 #212 (date argument + schedule); #136 needs owner.
- Tests: unit 1,827 passed, integration 156 passed, 11 new/retargeted mutants killed.

- PM 2026-10-04: advised DeepSeek/SumoPod for the Knowledge Extractor after the SYS-39 bake-off; token estimate in decisions/product-manager/knowledge-extraction-provider.md.

- PM 2026-10-04: handed SYS-39 (extract all news on DeepSeek, peak guard) to SDE; see handoff.md.

## SDE update 2026-10-04 (evening, "do the rest of the tickets")
- [x] Ready-for-qa with evidence: DBT-50 #214, SYS-69 #217, SYS-65 #211, SYS-75 #225 (new, found by the SYS-73 dry run).
- [~] Code done, waiting on the owner: OPS-38 #212 (register the 12:00 job; time decision), SYS-39 #125 (ADR-003; bake-off DeepSeek 0.960 run-to-run, 0.85-vs-Gemini gate not runnable on the free tier; prod migration; provider switch), SYS-73 #223 (dry run reported; apply path not written).
- [ ] Not done: SYS-74 #224 (needs a new idea first), SYS-41 #127, SRC-34 #124, SRC-47 #157, SRC-42 #145, SRC-40 #134, SRC-39 #133 (policy umbrella), DBT-19 #69, DBT-22 #73, DBT-01 #20. Owner-only: SRC-56 #205, SRC-03 #14, OPS-20 #136 choice.
- Tests: unit 1,976 passed, integration 165 passed; 12+24+7+7+6+3 new mutants killed (SYS-65 7, SYS-69 6, OPS-38 12, SYS-39 24, SYS-75 7, DBT-50 3).
- **Production DB untouched.** `migrate_api_usage_tokens.sql` is applied to `newsaggregator_test` only; production needs it (after a backup) before any extraction or newsletter run on this code.

## Owner decisions 2026-10-04 (late evening), executed
- SYS-39 gate accepted on evidence; prod migration applied (verified backup first); newsletter job registered at 12:00 ("NewsAggregator Newsletter", first run 2026-10-05); SYS-73 repair per source, DETIK first, after QA closes SYS-75.
- Next dev: set `KNOWLEDGE_LLM_PROVIDER=openai` + schedule off-peak extraction (owner go on the date), write the SYS-73 apply path. Watch: first newsletter run 2026-10-05 12:00.

## Night push 2026-10-04: P1/P2 (CTO/PM decided, dev built, QA verified against the tickets' wording)
- **Closed by QA (17 + 2 decided):** OPS-35, OPS-37, SYS-71, SYS-72, SYS-67 (sent back once, fixed), SYS-68, SYS-63, SYS-69, SYS-65, SYS-75, SYS-76, SYS-77, SYS-78, SYS-20, DBT-50/19/22/53/54; SRC-03 won't fix (CTO), SRC-56 re-prioritised P3.
- **Ready for QA, waiting on scheduled runs:** OPS-20 #136 (P1) and SYS-39 #125 (first nightly extraction 2026-10-05 21:00), SRC-57 (3 runs), SYS-64 (7 days), SYS-66 (PIKIRANRAKYAT cooldown ~10-09), OPS-38 (3 digests from 10-05 12:00). OPS-36 #209 waits for the owner to confirm the two Telegram messages of the drill.
- **Live now:** extraction on DeepSeek (4 workers) - 5,992 articles, $1.98, KB 54 -> 10,006 entities; jobs registered: Knowledge Extraction 21:00, Newsletter 12:00, DB Liveness every 15 min. 80,355 articles pending (~4 nights); lower KNOWLEDGE_DAILY_COST_LIMIT_USD from 8 to 3 afterwards.
- **Filed by QA:** DBT-53, DBT-54, SYS-76/77/78, SRC-58 #231, OPS-39 #232. Open and not started: SYS-73 apply path (per source, DETIK first), SYS-74, SYS-41, SRC-34, SRC-47/42/40/39, SRC-58, OPS-39, DBT-01.
- Tests: unit 2,061 / integration 172; QA mutation runs in clean copies: 69 + 61 + 8 killed, 0 survivors; 270 registered mutants all match exactly once.

## 2026-10-05 06:20: body repair done (SYS-73 closed)
- All 24 sources with polluted bodies repaired 03:19-06:09 WIB, before the 07:00 crawl: 35,547 articles rewritten, 165,319 chunk rows and vectors replaced, 0 failed. Verified: dry run over 86,347 articles 0 changed; store check all 11 zero; DETIK 46,196 L2 rows = 46,196 vectors; counters recomputed; chrome in search results 10 -> 3 and 4 -> 0.
- Built for it: `repair_boilerplate_bodies.py --apply --source NAME` (backup, vectors, one SQL transaction, re-chunk with one FAISS flush per block, recount), 11 integration + 10 unit tests, 13 mutants killed. Runbook in OPERATIONS.md.
- DBT-55 (#233) found and closed: 6 unit tests failed on Mondays (the weekly audit day). Tests: unit 2,087, integration 183.
- PM 2026-10-05: newsletter 5-minute edition scoped (critique + UX copy + owner decisions); tracker #244, tickets SYS-80..84 (#236, #237, #239-#241), OPS-41..43 (#238, #242, #243). Not started; build order in decisions/product-manager/newsletter-5min-edition.md.
- Still waiting for scheduled evidence: #136 and #125 (first 21:00 extraction, which also re-extracts the 2,530 reset articles), SRC-57, SYS-64, SYS-66, OPS-38. Backups of the repair: 55 GB in `backups/` (24 x 2.1 GB), prune after a few days.

## SDE 2026-10-05: newsletter 5-minute edition (tracker #244)
- [x] Built: SYS-80 #236, SYS-81 #237, OPS-41 #238, SYS-82 #239, SYS-83 #240, SYS-84 #241, OPS-42 #242, OPS-43 #243; SYS-85 #245 (found while building). Commits 654a81e, 5dacec7, a90067e, 81f7483.
- [x] Replayed on 2026-10-04 / 10-03 / 09-28 (four runs; EXPERIMENTS.md 2026-10-05). Edition 869-949 words, 7 phone pages, document checks clean.
- [x] Owner decision: phone page 105x228 mm, a story may continue after its title + first sentence (OPS-42's <= 6-page target replaced).
- [ ] Missed targets, owner/PM: SYS-82 first-try 46-62% (target 90); after retry 92.7% on 09-28 (target 95); SYS-83 coverage 4/6 on 09-28 and one duplicate on 09-28. See decisions/sde/newsletter-5min-edition.md "Open".
- [ ] Owner: hand-check 20 stories (SYS-82), read one edition on the phone (SYS-83, OPS-42). QA: three scheduled 12:00 runs (OPS-43).
- Tests: unit 2,292 passed, integration 183 passed; newsletter mutants in qa_mutation_runner.py (results on the tickets).

## CTO 2026-10-05 (evening): edition decisions, owner aligned
- [x] Four decisions recorded in `decisions/cto/newsletter-5min-edition.md`: no non-finance quota (general briefing, finance first); judul ask 10 accept 12; the day's 6 largest stories guaranteed; word-overlap echo guard. SYS-82's 90% first-try target retired; cost criterion = newsletter <= $0.05/day.
- [x] Built in the same session (owner: "build it now"): commit 5fe7859; unit 2,302 passed.
- [x] Replay v5: after-retry 100 / 98.9 / 99.0%, 833-994 words, 6 largest stories 6/6 each day, no repeat after the echo refinement (776e6e9). 67 newsletter mutants killed. SYS-82 #239 and SYS-83 #240 ready-for-qa: all 9 tickets with QA.

## QA 2026-10-05 (night): newsletter 5-minute edition (tracker #244)
- **Closed:** SYS-81 #237, OPS-41 #238, SYS-84 #241, SYS-85 #245.
- **Sent back:** SYS-80 #236. The v5 re-render of 2026-10-04 again links "10 Saham Paling Babak Belur" under a Haji Isam headline, with a FORU bullet from it. The Done-when names exactly this link.
- **Held:**
  - SYS-82 #239: waits on the owner's hand-check of 20 stories.
  - SYS-83 #240: waits on the owner's phone read and the first scheduled run, and needs SYS-86 fixed.
  - OPS-42 #242: waits on the owner's phone confirmation.
  - OPS-43 #243: needs 3 scheduled 12:00 runs, the first on 2026-10-06.
- **Filed:**
  - SYS-86 #246 (P2): the echo guard hides distinct events.
  - SYS-87 #247 (P3): the number guard ignores the decimal position.
  - OPS-44 #248 (P3): a failed PDF upload leaves the reader promised a PDF.
  - SYS-88 #249 (P3): HTML entities in 311 headlines.
  - SYS-89 #250 (enhancement): the edition repeats the previous day's.
  - DBT-56 #251, DBT-57 #252, DBT-58 #253 (P3): test gaps found by mutants.
- **Release readiness:** the 2026-10-06 12:00 run can ship. Nothing blocks delivery, and the archive is unchanged in scope. Tracker #244 cannot close until SYS-86 and SYS-80 are fixed and the 7-edition success criteria are met.
- **Tests:** unit 2,303 passed; integration 183 passed. QA's own set: 44 passed, 5 failing on SYS-86/87. QA mutants: 49/57 killed (5 real gaps filed, 3 equivalent). Report: `reviews/2026-10-05-qa-report.md`.

## SDE 2026-10-05 (night): QA's tracker #244 findings fixed
- [x] SYS-86 #246 echo guard (468b75d, 41a3ab6): story_words; event words + a shared name; a one-sided name is never an event word; Title Case judul marks no names. Untuned days (09-24 partial, 09-25, 09-29, 09-30, 10-02): 1 wrong hide (dana pensiun), at the Done-when limit.
- [x] SYS-80 #236 (79c4586, c161ec3): subject check (a name or 2 judul words), refused on the first answer and demoted on the retry; numbers held to `terkait`. 10-04 re-render: no "10 Saham", no TVONENEWS link. After retry on the valid v7 days: 100% / 98.9%.
- [x] SYS-87 #247 numbers by value; OPS-44 #248 follow-up "PDF tidak tersedia"; DBT-56/57/58 tests; DBT-59 #254 (found: vacuous test) fixed.
- [x] SYS-88 #249 code done (ingest, page title, newsletter read path); backfill applied 2026-10-06 05:59 with the owner's approval: 2,410 rows, entity query 0, backup `backups/sys88_headlines_20261006_055952.json`. Ready for QA.
- Tests: unit 2,387 passed; integration 183 passed; 112 newsletter mutants (see ticket comments).
- **Blocker for 2026-10-06 12:00: the SumoPod prepaid balance ran out ~23:00** (owner 2026-10-06: not topped up; resolved by a top-up, no code change). The 21:00 extraction stopped (6,081/6,090, $2.04); the newsletter will get no summaries (headline lists, no edition) unless the balance is topped up first. The replays of this session spent part of it (~15 replayed days, roughly $0.2-0.3).
