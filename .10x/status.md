# Project Status

## Project: NewsAggregator
**Current Phase:** Implementation (dev): P1/P2 fixes + newsletter. Design approved by owner choice of DeepSeek; spec + ADR-001 written.
**Last Updated:** 2026-10-08 (evening) by sde
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

## SDE 2026-10-06: P3 bug burn-down (decisions/sde/p3-bug-burndown-2026-10-06.md)
- [x] SRC-58 #231: dead branches skipped (NXDOMAIN, hostless <loc>) or reported as gone (404, bad redirect). PIKIRANRAKYAT sitemap phase 147 s -> 50 s live. Ready for QA.
- [x] OPS-39 #232: orphaned crawl_log rows reported at 05:30 (per-task limit) and closable; the 5 production rows closed (owner approved). Ready for QA.
- [x] DBT-01 #20: requirements.txt = venv freeze; SitemapDTO.timestamp Optional. Ready for QA.
- [x] SYS-90 #255 (found): an int yyyymmdd was read as Unix seconds (193 articles with posted_at 19700823); fixed at the DTO, rows repaired (owner approved). Ready for QA.
- [ ] SRC-47 #157: owner-deferred 2026-09-25; re-measured read-only for the owner's re-decision.
- Tests: unit 2,434 passed; integration 187 passed; 21 new mutants killed.

## Ops 2026-10-06 (night): SumoPod key unblocked
- The key's own $5 "Max budget" (not the account balance) blocked every call 2026-10-05 ~23:00 -> 2026-10-06 22:28: the 10-06 12:00 newsletter went out as headlines only, and the 21:00 extraction did 0/8. The owner removed the cap ("the $5 budget is no more a constraint").
- Catch-up (owner chose both): 2026-10-05 newsletter rebuilt 22:29-22:42, 92/92 summaries, edition 931 words / 8 top stories / 0 hidden lines, message and edition PDF sent; extraction catch-up started 22:42 (log scheduled_extraction_2026-10-06_2242.log).

## QA 2026-10-06 (night): the P3 burn-down and the #244 fixes verified
- **Closed (12):** SYS-90, OPS-39, DBT-01, SYS-86, SYS-80, SYS-87, OPS-44, SYS-88, DBT-56, DBT-57, DBT-58, DBT-59.
- **Held:** SRC-58 #231, until the 2026-10-07 07:00 crawl.
- **Filed (4):** SRC-59 #260 (P2, INVESTORID news sitemap 404), SYS-91 #257, DBT-60 #258, OPS-46 #259 (P3).
- **Tests:** unit 2,434 / integration 187; mutants 84/84 killed (69 dev + 15 QA `qa1006_*`). Report: reviews/2026-10-06-qa-report.md.
- **Integration tests leak into the real Telegram outbox (OPS-46):** QA deleted the 10 test lines its own run queued.

## PM 2026-10-07: RAG search redesign is the next top priority (owner)
- Tracker #272 (label `priority: next`, new label `area: web`). 11 tickets:
  - bugs: SYS-92 #261 (P2), SYS-93 #262 (P2, security), SYS-94 #263 (P2), SYS-95 #264, SYS-96 #265, SYS-97 #266 (P3);
  - enhancements: SYS-98 #267, SYS-99 #268, SYS-100 #269, SYS-101 #270, SYS-102 #271.
- Build order and the full copy/prompt: decisions/product-manager/rag-search-redesign.md.
- Owner decisions open: SYS-98 provider (PM recommends DeepSeek via the shared Summarizer); SYS-102 mockup approval.

## Dev 2026-10-07: RAG search redesign (tracker #272), design + planning done
- Owner decision: SYS-98 answers on DeepSeek via SumoPod (`RAG_LLM_PROVIDER=openai`).
- ADR-005 accepted: answers through `Summarizer.complete()`, usage under `web:<model>` with its own daily cap, explicit answer states, two-step turns (sources first, then the answer), filters on DB metadata.
- Plan: decisions/engineering-manager/rag-search-redesign.md (mockup first for SYS-102's approval, then steps 1-11).

## Dev 2026-10-07: RAG search redesign built (tracker #272), phases 4-6 complete
- **Built (all 11 `status: ready-for-qa`):**
  - defects SYS-92..SYS-97 (#261-#266);
  - the answer: SYS-98 (DeepSeek, owner) and SYS-99;
  - copy, filters, look: SYS-100, SYS-101, SYS-102 (mockup approved by the owner).
- **Commits:** ceb73cf, d2b48d4. **ADR:** ADR-005.
- **Tests:**
  - unit 2,609 passed; integration 193 passed; RAG mutants 42/42 killed;
  - keyboard e2e 14/14 (headless Chrome over CDP).
- **Live:**
  - 10-question replay on DeepSeek, 10/10 clean, ~$0.0003-0.0004 per answer;
  - 1 question on Gemini;
  - warm-up 14.8 s; first retrieval 62 ms;
  - 8 screenshots (375/1280, light/dark).
- **Filed:** SYS-103 #273 (P3): FTS ANDs every question word, so it contributes 0-1 hits per question. Not started.
- **Reviews:** `reviews/2026-10-07-qa-report.md`, `reviews/2026-10-07-security-review.md` (local-only sign-off).
- **Owner:** restart the :8000 web app (one worker) to get the new page.

## Dev 2026-10-07: SYS-103 keyword search (ADR-006), design + plan
- Owner weighed Elasticsearch, then chose the IDF-weighted keyword match ("lets do that"): the problem is relevance, not speed.
- Design: decisions/architect/rag-keyword-search.md. df from `pg_stats.most_common_elems` (30 ms) plus exact counts for rare words.
- Plan:
  - [x] 1. `web/keywords.py` (terms, KeywordQuery, DocFrequency) + unit tests
  - [x] 2. `_fts_search` / floor / re-rank (`keyword_score`, `RAG_MIN_KEYWORD_COVERAGE`) + tests
  - [x] 3. integration test in `newsaggregator_test`
  - [x] 4. `sys103_*` mutants
  - [x] 5. replay (Done-when: fts on >= 8/10, BI decision in the top 5, < 400 ms) + EXPERIMENTS + OPERATIONS
  - [x] 6. ticket evidence, `status: ready-for-qa`

## Dev 2026-10-07: SYS-103 built (c69d34d), ready for QA
- **Done-when:** fts=20 on 11/11 replay questions (was 0-1); the BI-Rate decision at ranks 3-5; the unit test on the BI question.
- **Latency:** retrieval 108-358 ms warm; up to 1.3 s on cold Postgres pages (was 62-125 ms with an empty FTS).
- **Tests:** unit 2,655 / integration 198; 25/25 `sys103_*` mutants killed.
- **Open, not fixed:** no stemming ("suku bunga terbaru" → forecasts); opinion pieces holding every word can outrank news.
- **Owner:** restart :8000 to pick up both #272 and SYS-103.

## QA 2026-10-07 (evening): tracker #272 + SYS-103 verified independently
- **Closed (13):** SYS-92..SYS-103 (#261-#271, #273) on their Done-when; SRC-58 #231 on the 07:00 + 19:00 crawl notes.
- **Filed (8 + test gaps):**
  - SYS-104 #274 (P2): follow-ups retrieved without the thread.
  - SYS-105 #275 (P2): 1-word trailing chunks are semantic hubs.
  - SYS-106 #276 (P2): keyword-only hits never reach the top 5 (0 of 95).
  - SYS-107 #277 (P2): candidates ignore dates.
  - SYS-108 #278 (P3): the df cache keeps a 0.
  - SRC-60 #279 (P2): kumparan reader posts stored as news.
  - SRC-61 #280 (P3): kumparan chrome.
  - DBT-61 #281 (P3): integration tests vs the crawl's run lock.
  - Plus the `qa1007_*` test-gap ticket.
- **Tests:** unit 2,655; integration 198 (8 false failures while the crawl held the lock). Dev mutants 67/67 killed; QA mutants: see the report.
- **Held:** OPS-43 at 1 of 3 valid 12:00 runs (10-07); OPS-20/SYS-39 wait for tonight's 21:00 extraction. SRC-59 is still 404 and not worked.
- **Owner:** restart :8000 (it still runs pre-ceb73cf code).
- **Health:** the UI is done; retrieval quality (SYS-104..107, SRC-60) is the next work.

## SDE 2026-10-08: QA's retrieval findings fixed (ADR-007)
- [x] Ready for QA: SYS-104..108 (#274-#278), SRC-60 #279, SRC-61 #280, DBT-61 #281, DBT-62 #282, OPS-46 #259; found+fixed SYS-110 #284, DBT-63 #285; filed SYS-109 #283 (not fixed).
- [x] Owner-approved production writes: SRC-60 settle, SRC-61 KUMPARAN repair, SYS-105 re-chunk (pg_dump first).
- [ ] Owner: unblock the SumoPod key (401 since today; page answers, 21:00 extraction and 12:00 newsletter fail), restart :8000.
- [ ] QA: verify; watch the 19:00 KUMPARAN out-of-scope note.
- Details: decisions/sde/rag-retrieval-quality.md; handoff.md.

## SYS-109 #283 (chunks fit the encoder window): design + planning done 2026-10-08
- Owner: "design it and fix it directly after the design is finished".
- Measured (probe_encoder_window.py): 80-word windows late recall@1 0.137 -> 0.750, early 0.730 -> 0.753; MiniLM window raise and e5-base rejected.
- ADR-008; spec `.10x/specs/2026-10-08-sys109-chunks-fit-encoder-window-design.md`; DBT-64 #286 filed (mention FK indexes).
- Plan: decisions/engineering-manager/chunks-fit-encoder-window.md (7 tasks; production run overnight after the 19:00 crawl).
- [x] SYS-109 implementation done (b25dd36, 3aea301, 6ddae23): unit 2,765, integration 207, 7/7 mutants; production run next (dump -> migration -> `--all --apply --until 06:15`).
- [x] Production re-chunk done 2026-10-09 00:30. 100,466 articles, 0 failed; 737,682 L2 rows, 0 over 80 words; store consistency zero; late recall@1 0.020 → 0.360.
- [x] Found and fixed: SYS-111 #287 (`--until` past = today: deleted before stopping) and OPS-47 #288 (worktree teardown deleted 23 venv packages through the junction; repaired, `pip freeze` == requirements.txt).
- [x] Ready for QA: SYS-109 #283, DBT-64 #286, SYS-111 #287, OPS-47 #288.
- [ ] SYS-112 #289 (filed): re-tune the recency gate/floor on the windowed scores ("Menkeu sekarang", BI decision).
- [ ] Owner: restart :8000 (NEWS_L2 now 750k vectors, ~7.6 GB per web process); unblock the SumoPod key. The 21:00 extraction was skipped on 2026-10-08 (run lock).

## 2026-10-11: entity links (feature `entity-links`) -- Phase 0 brainstorm done, spec awaiting owner review
- Goal: links between KB entities -> listed companies exposed to news their price has not reflected; newsletter uses the links too.
- Spec: `specs/2026-10-11-entity-links-design.md` (owner decisions 1-9 inside). Evidence: EXPERIMENTS.md 2026-10-11.
- KB state 2026-10-10: 59,723/114,524 articles extracted (~3 nights left at ~20k/night, ~$6.8/night); 88.6k entities, 482k mentions, 125 aliases; heavy duplication (PGAS x17).
- Next: owner reviews spec -> Phase 1 (CTO/PM decisions, PRD non-goals updated) -> ADR -> tickets. Waiting on owner: price-DB access + 4 facts (adjusted? volume/value? suspension/board? existing calcs?).
- 2026-10-12 spec revision (owner said yes):
  - merge undo is exact (deleted duplicate mentions are kept in `entity_merges`);
  - `extract_links` runs a ~300-article pilot, and the 85% precision gate is checked on it before the ~$20 full pass;
  - new section "Production writes and their order": migrations A -> merge -> migrations B (the unique ticker index) -> link pass.
- 2026-10-12 tickets filed (owner: "raise tickets to do all those things first"): tracker #315; SYS-113..SYS-136 = #290..#313; OPS-48 = #314.
  - SYS-113 (docs: PRD non-goals, Phase 1 CTO/PM, ADR-009, Phase 3 plan) comes before any code.
  - SYS-120 PriceSource is blocked on the owner (DB access + 4 facts).
  - No code written yet.
- **Parked by the owner on 2026-10-12 ("leave it for now").** Resume at SYS-113 when the owner picks it up again.

## QA 2026-10-12: SDE's 2026-10-08/09 handoff + held tickets verified independently
- **Closed (24):**
  - SYS-105/106/107/108/109/110, SRC-60/61;
  - DBT-61/62/63/64, OPS-46/47;
  - OPS-43, OPS-20, SYS-39, SRC-57, SYS-64, SYS-66, SYS-70, OPS-40, DBT-51/52.
- **Sent back (2):**
  - SYS-104: a follow-up that changes topic retrieves the old topic, 5/5 pairs;
  - SYS-111: `repair_boilerplate_bodies` re-resolves `--until` after the deletes.
- **Held:** SYS-79 (no blip yet), SYS-82/83 + OPS-42 (owner reads), SYS-40 (owner + SRC-34).
- **Filed:**
  - SYS-137 #316, SYS-138 #317, DBT-65 #318, DBT-66 #319 (all P3);
  - **SYS-139 #320 (P2):** VIVA full_text killed at 1,200 s two runs in a row (last batch); 538 saved articles have no vectors.
- **Tests:**
  - unit 2,770; integration 210, run under a held real run lock;
  - dev mutants 116/120 killed (2 equivalents, 1 killed by the full suite, 1 stale and retargeted);
  - QA's 48 own tests (1 = the SYS-111 repro); QA mutants: 4 real gaps → DBT-66.
- **Owner:** the SumoPod key has been blocked since 10-11 (account budget $22.50 exhausted by extraction). The newsletter, extraction and search answers degrade until it is unblocked or topped up.
- Report: `reviews/2026-10-12-qa-report.md`.

## Ops 2026-10-12: SumoPod topped up
- The owner topped up twice; the balance is **$22.50**. The key works again: a test call returned 200 after the 401 "blocked" on 10-11.
- The 10-10 block was the prepaid balance running out ("Spend=22.5, Budget=22.5"), not a separate limit on the key.
- **Plan, at the measured $0.34 per 1,000 articles:**
  - `KNOWLEDGE_DAILY_COST_LIMIT_USD` stays at 8;
  - nights 10-12/13/14 extract ~20k each (`KNOWLEDGE_MAX_PER_RUN`), ~$20.5 in total, which clears the backlog (50,462 + new);
  - about $2 is left on 10-15. The steady cost after that is ~$1.20/day (~$36/month).
- **Owner decision (`decisions/cto/llm-budget.md`):** the project's LLM budget is ~$100, every article is extracted, and monetization is deferred.
- **Action due 10-15:** set `KNOWLEDGE_DAILY_COST_LIMIT_USD=1.5` in `.env` before the 21:00 run. The owner tops up "later": ~$2 is left on 10-15, so **a top-up is due by ~10-16** or the 10-17 newsletter fails.
