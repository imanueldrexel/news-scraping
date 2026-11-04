# Project Status

## 2026-11-04: SYS-197 validity settled (ADR-026/027)
- [x] The owner could not judge the ADR-025 y/n. Switched the blind labeller to Gemini (ADR-026): one y/n agreement 33/40 failed, but 4 of the 7 were rubric-definition disputes.
- [x] Split validity into label_ok (gated: 37/40 holds; the owner ruled the 3 meaning disagreements: 1 Gemini, 2 Claude) and type_ok (Claude; a misfit goes to the `other` bucket). ADR-027.
- [x] All 5 families keep on label_ok. `tests/fixtures/nli_eval/handcheck_final.csv` written for SYS-199. Scorer 14 + labeller 7 tests; 5/5 scorer mutants killed.
- [x] SYS-197 filter: `filter_nli_pairs.py` moves 142 type misfits to `other` (denial 92, cause 50); hand check 8/9 caught, 0 false; generator seed rule fixed; `pairs.jsonl` written. SYS-197 ready-for-qa.
- [x] SYS-198: 12:00 edition wrote 20 rows (20/20 scored), +124.5 s; ready-for-qa.
- [x] Filed SYS-200 #430: natural set from live `nli_shadow` rows (needs about 10 editions).
- [ ] SYS-199 #429: run eval_nli.py on `pairs.jsonl` with the arm A model; report per type plus `other`; validity from 2 LLM labellers + 3 owner rulings.

## 2026-11-03: finish the NLI track + close the qa-passed set (owner: "finish as suggested")
- [x] Machine was off 2026-10-26 evening -> 2026-11-03 22:18: no crawl, extraction or edition 10-27..11-02. The catch-up newsletter wrote an EMPTY 11-02 digest (correct). Not a defect.
- [x] QA: 9 qa-passed tickets closed with the 10-20 evidence (SYS-79, SRC-59, SYS-139, SYS-147, SYS-149, SYS-193, DBT-72, DBT-73, DBT-75).
- [x] SYS-197: owner chose ADR-025 (Claude pre-labels, owner blind 40). Claude's labels: end 40/40, schedule 39/40, hedge/cause/denial 34/40 (borderline). Scorer `score_nli_handcheck.py` + 6 tests, 3/3 mutants killed.
- [ ] Owner: fill `tests/fixtures/nli_eval/handcheck_owner_blind.csv` (40 rows, valid y/n), then `score`.
- [ ] SYS-198: prod migration applied 10-25, NLI_SHADOW=1 set, 0 rows so far (the 10-26 edition built 0 arcs: SumoPod connection errors). Check `nli_shadow` after the 2026-11-04 12:00 edition, then post evidence + ready-for-qa.
- [ ] Generator filters (denial seeds without a denial verb; cause edits after 'sehingga') before SYS-199.
- Fixed in passing: tests/fixtures/nli_eval/*.jsonl were CRLF on disk (index LF), re-checked out; unit 3,999 / 5 skipped.

## NLI faithfulness (2026-10-25): design approved, planning next
- [x] Brainstorm, spec `.10x/specs/2026-10-25-nli-faithfulness-design.md`, ADR-024, tickets SYS-197 #427 / SYS-198 #428 / SYS-199 #429.
- [x] Planning complete (EM + senior-engineer files). Implementation started: SYS-198 T1-T5 and SYS-197 E1-E3 (no spend). E4 pair generation + E5 hand check wait on the owner.
- [x] Implemented: SYS-198 code + tests + mutants; SYS-197 harness + golden fixture. Waiting on owner: prod migration, NLI_SHADOW=1 + NLI_MODEL on the 12:00 job, pair-generation spend, hand-check time, torch CUDA build question.
- [ ] (old line) SYS-197 (eval set) and SYS-198 (shadow) in parallel; SYS-199 after both.
- Owner decision: NLI regardless of Indonesian accuracy; shadow first; supersedes gate-lexicon decision 7.

## Project: NewsAggregator
**Current Phase:** QA 2026-10-20: whole queue audited (26). 9 qa-passed, 13 qa-failed, 4 held (owner reads). New qa-defects #413-#425. Next: brainstorm a general design for the lexical gates (owner agrees the list fixes do not close the class).
**Last Updated:** 2026-10-20 by QA
**Health:** At Risk (SYS-181 P1 class still prints a swapped-subject cause in the gate; arcs=1 live; the 10-19 edition had no false fact)

## Progress

### QA 2026-10-20: the whole ready-for-qa queue
- [x] 26 tickets: qa-passed #234 #260 #320 #337 #339 #344 #345 #347 #394; qa-failed #327 #328 #331 #338 #342 #343 #376 #381 #385 #387 #390 #392 #393; held #126 #239 #240 #242.
- [x] 13 qa-defects closed as verified, #405 not-a-defect, #401 open (owner: option a). New #413-#425.
- [ ] Brainstorm: a design for the closed word lists (causal/hedge/denial/end/plan/-nya) before more send-back fixes.
- Report: `.10x/reviews/2026-10-20-qa-report.md`.


### SDE 2026-10-20: QA's 2026-10-19 qa-defects (#398-#412) -- 13 FIXED, 2 DISPUTED; 11 parents back to ready-for-qa
- [x] #398 #399 #400 #402 #403 #404 #406 #407 #408 #409 #410 #411 #412 FIXED; #401 FIXED except "terimbas" (DISPUTED, conflicts with SYS-184's test); #405 DISPUTED (refuses the live MSCI true end).
- ADR-022 (follow-up: -nya word after "yang" is no reference; object phrase to clause end), ADR-023 (arc guards). Measured live: risk/object/held-out sets equal, QA's switches 6/20 -> 17/19.
- Feature file: `.10x/decisions/sde/qa-1019-sendbacks.md`. Committed on `dev`, NOT pushed (dev is 300+ commits ahead of origin; owner's call).

### QA 2026-10-19: audit of the 10-18 arc queue + 10-19 web queue
- [x] 10 closed with evidence comments.
- [x] 15 qa-defects filed (#398-#412); 11 parents `status: qa-failed`, 10 closed parents `status: qa-passed`.
- [ ] Dev: fix #398-#412; QA re-runs `scripts/experiments/qa_2026_10_19/defects/` and closes each qa-defect.
- Report: `.10x/reviews/2026-10-19-qa-report.md`.


### SDE 2026-10-19: QA's 2026-10-13 queue -- done, 8 ready-for-qa (e6637a9, 6c934c0)
- [x] SYS-194 [x] SYS-144+145 [x] SYS-146 [x] DBT-60 [x] DBT-70 [x] DBT-71 [x] SRC-62
- Unit 3,879 / 5 skipped; integration 225 / 1 skipped; QA file 10-13: all SYS-144/145, DBT-60, DBT-67/70 reds green (SYS-143's 5 noted-not-filed stay red, as at HEAD).
- Mutants (copy): 22 follow-up/keyword + 9 DBT-60 + 2 DBT-70 + 3 SRC-62 + QA's 4 DBT-71/68: all KILLED; qa1013_dbt60_no_strip retired (equivalent).
- Production (read-only): QA held-out B 22 -> 30/35, held-out sets 28 -> 33/40 and 12 -> 15/30, other sets equal; 1 pair worse = ADR-021's accepted cost. SYS-146 29 -> 36; "Siapa pemimpinnya Danantara?" 2/5 (SYS-195). Replay identical.

### SDE 2026-10-19: QA's 2026-10-13 queue -- design + plan
- Owner (2026-10-19): ADR-021 "Anaphor gate + list" for SYS-144/145; SYS-146's off-subject ranking is a separate ticket (SYS-195 #397).
- Measured before deciding (production, read-only, no model call): `scripts/experiments/sys144/measure_name_gate.py` -- HEAD vs list vs name gates on 9 pair sets, two held-out sets written before their runs; `sys144/mine_nya_adverbs.py` (20k articles); `sys146/measure_nya_terms.py` (29 -> 35 on-topic).
- Filed: SYS-194 #396 (FTS ORDER BY has no unique last key: same question, different cards), SYS-195 #397.
- Plan: engineering-manager/qa-1013-queue.md.

### SDE 2026-10-18: QA's 10-18 queue -- done, 13 ready-for-qa
- **Owner decision 2026-10-18 (evening): keep `NEWSLETTER_ARCS=1`** for the 10-19 12:00 edition on the new gate code. Grounds: the new code is strictly stricter than what ran live 10-17/10-18 and fails closed to the plain story; the guards raised 0 exceptions on 6,231 real articles (EXPERIMENTS.md, fuzz_gate_on_corpus.py); SYS-152's measurement needs live sebab logs. QA keeps its sentence-by-sentence check; on the first false fact, set 0.
- Owner: SYS-188 every word of a half covered; SYS-189 gate with a purpose exemption (membuat/mendorong/menekan); SYS-192 any hedge word.
- ADR-020 (causal) + architect "2026-10-18 (dev)" (time checks: SYS-186/191/193, SYS-177, SYS-190).
- [x] SYS-188+181  [x] SYS-189  [x] SYS-185+192  [x] SYS-183+187  [x] SYS-186+191+193  [x] SYS-177  [x] SYS-190  [x] DBT-83 (ac5566a..e3ab148)
- Unit 3,804; QA files 10-14..10-18 724/724 (10-18 104/104); arc registry 339: 339/339 KILLED.
- Replays: causes 12/18 -> 9/26 backed (6 lost = owner's every-word rule; 8 new SYS-189 spans, 3 backed); end points 12/0 refused; running spans 6/0; periods 22/0.

### QA audit 2026-10-18: the SYS-152 send-back queue (ADR-019, SYS-186, SYS-174/177/178/179)
- Closed: SYS-182, SYS-184, DBT-82, SYS-174, SYS-178, SYS-179. Sent back: SYS-181 (name room; anaphor with own subject), SYS-183 (fronted list), SYS-185 (batal/membantah/tidak benar), SYS-186 (MSCI rephrased), SYS-177 (cue list/window). Held: SYS-152 (>= 90% unmeasured).
- Filed: SYS-188 #389 P1 (swapped subject), SYS-189 #390 P1 (didorong/dipengaruhi/seiring unchecked), SYS-190 #391, SYS-191 #392, SYS-192 #393, SYS-193 #394, DBT-83 #395.
- Unit 3,674; registry 87/87 KILLED; QA mutants 8/16 (4 real -> DBT-83); QA file `scripts/experiments/qa_2026_10_18/test_qa_1018.py` 41 green / 63 red; recheck_causes 12/18 reproduced. Report: reviews/2026-10-18-qa-report.md

### SDE 2026-10-17 (afternoon): QA's SYS-152 send-back queue -- done, 11 ready-for-qa; SYS-187 #388 filed
- Design: ADR-019 (owner: strict per half; OMC becomes an accepted false refusal) + architect/newsletter-story-arcs.md "2026-10-17 (dev)".
- [x] SYS-152 direction + SYS-181  [x] SYS-186  [x] SYS-182  [x] SYS-184  [x] SYS-183  [x] SYS-185  [x] DBT-82 (4018876 + SYS-186 commit)
- Causal recheck after: 12/18 backed (lost OMC = owner, Dadang = accepted, Padang 'belum surut' = true catch); 59+6 mutants KILLED. SYS-186 replays: 12 end points, 0 refused; live MSCI refused on its real source.
- [x] SYS-174 rework  [x] SYS-177  [x] SYS-178  [x] SYS-179 -- QA's 10-14..10-17 arc files all green (the 27 reds fixed); 66 related mutants KILLED; replays 6 running spans (all latar) 0 refused, no new future time
- Replay recheck before: 18 causal words in v4/v5/v6, 15 backed, 3 refused (MK, Ojol v5, karhutla v4).

### QA audit 2026-10-17: SYS-152 sent back, DBT-81 closed; SYS-181..185 + DBT-82 filed
- First live arc edition: 1 false fact (MSCI freeze 'hingga November 2026', source H2-2027), filed as SYS-186 #387 P1; QA recommends NEWSLETTER_ARCS=0 (#340).
- Unit 3,537; dev mutants 20/20 KILLED; QA mutants 9/17 (DBT-82); QA file `scripts/experiments/qa_2026_10_17/test_qa_sys152.py` 9/34 green (25 red = SYS-152 direction + SYS-181..185, all `kept` through parse). Report: reviews/2026-10-17-qa-report.md

### SDE 2026-10-17: SYS-152 built (ADR-018), ready-for-qa; DBT-81 fixed
- causal_check.py + story_arc `sebab` gate; 43 tests, 20/20 mutants, unit 3,537; offline replay 15/18 backed, MK refused. Details: decisions/sde/newsletter-story-arcs.md.

### 2026-10-17: SYS-152 design = ADR-018 (owner accepted); SYS-180 #379 shadow judge filed
- Prompt asks for a quote, code decides on both halves of the sentence, the judge only logs. Dev builds SYS-152 first.

### Owner 2026-10-17: NEWSLETTER_ARCS=1, SumoPod $6.35, extraction cap kept at $1.50

### QA 2026-10-17: SYS-150 ship gate
- Owner's blind A/B on arcs-v5: arcs won 5/5. QA hand-check first pass: same_thread 40/43 (93%); attributed 5/6. The MK arc invents a causal link, so SYS-152 goes to P0, with a design note: rule (b) on the cause clause alone passes it. Evidence on #340 and #342.

### QA audit 2026-10-16 late (eeb205c, HEAD 5445c2e)
- Unit 3,493. QA file `scripts/experiments/qa_2026_10_16_late/test_qa_1016_late.py`: 152/179 (27 red = the SYS-174 send-back + SYS-177/178/179, every one `kept`). Registry 25/25, QA night 18/18, QA late 11/11 KILLED. Replays reproduce (6 running spans, 0 refused). Report: reviews/2026-10-16-qa-report-late.md


### SDE 2026-10-16 (late night): QA's night queue -- done, ready-for-qa
- Design: architect/newsletter-story-arcs.md "2026-10-16 (dev, late night)". SYS-174 is judged by field: today never backs a running span; in the agenda only a day ahead does. The stricter all-field rule refused 6/39 true replay arcs.
- [x] SYS-171 rework  [x] SYS-174  [x] SYS-175  [x] SYS-176
- QA files 407/407 (night 140/140); 25 new or retargeted registry mutants + QA's 18 KILLED; replays HEAD vs tree identical. Details: decisions/sde/newsletter-story-arcs.md "2026-10-16 (late night)".

### QA audit 2026-10-16 night (1eff4b1, HEAD 98bb7c0)
- Unit 3,453. QA file `scripts/experiments/qa_2026_10_16_night/test_qa_1016_night.py`: 123/140 (17 red = the SYS-171 send-back + SYS-174/175/176). Registry 29/29 KILLED; QA mutants 17/18 by the dev suites (the 1 left -> the SYS-171 send-back). Replays and metrics reproduce. Report: reviews/2026-10-16-qa-report-night.md

### SDE 2026-10-16 (night): QA's evening queue -- done, ready-for-qa
- Design: architect/newsletter-story-arcs.md "2026-10-16 (dev, night)"; owner: "ke depan" windows count (SYS-171).
- [x] SYS-169 rework  [x] SYS-171  [x] SYS-172  [x] SYS-173
- QA files 267/267 (evening 68/68); unit 3,453 passed; 51/51 arc registry mutants KILLED in a copy; replays: no arc newly refused, metrics identical. Details: decisions/sde/newsletter-story-arcs.md "2026-10-16 (night)".

### QA audit 2026-10-16 evening (ee1b6cd + 7712d4f)
- Unit 3,421; QA file `scripts/experiments/qa_2026_10_16_eve/test_qa_1016_eve.py` 54/68 (14 red = SYS-169 send-back + SYS-171/172/173); dev arc mutants 26/26, DBT-80 retargets 25/25, QA mutants 14/16 by dev suites (2 -> SYS-169, SYS-172). Report: reviews/2026-10-16-qa-report-evening.md

### SDE 2026-10-16 (evening): QA's 10-16 queue -- done, ready-for-qa
- Design: architect/newsletter-story-arcs.md "2026-10-16 (dev)"; owner chose SYS-169 = refuse as `date`, SYS-168 = no bare "bulan/tahun ini".
- [x] SYS-169+168  [x] SYS-170  [x] SYS-167  [x] DBT-79  [x] DBT-80
- QA files 10-14/15/16 all pass; 28 arc mutants + 25 DBT-80 retargets KILLED; registry 0 stale, hygiene test guards it. Offline: v4 Padang "pekan ini" now refused (true catch). Details: decisions/sde/newsletter-story-arcs.md.

### QA audit 2026-10-16 (7e5a21a + SYS-161 fcda81c)
- Unit 3,344; QA file `scripts/experiments/qa_2026_10_16/test_qa_1016.py` 35/55 (20 red = the 4 new SYS tickets); dev mutants 12/12 + sys161 6/6 KILLED, QA's qa16 5/9 by dev suites (4 -> DBT-79); v4/v5/v6 metrics reproduce. Report: reviews/2026-10-16-qa-report.md

### SDE 2026-10-16: QA's 10-15 queue
- SYS-164 #359 (rework): "sejak <bulan>" is a frame, not an anchor (`arc_style._is_frame`). SYS-165 #361: an agenda repeating a future time ("minggu depan") is dropped. SYS-166 #363 (new, found while building SYS-165): "minggu depan"/"pekan ini" agendas were dropped as guesses. DBT-78 #362: QA's 5 survivors guarded and registered. All ready-for-qa.
- QA file 60/60; unit 3,344 passed (5 skipped); arc mutants 87/87 KILLED in a scratch copy; v4/v5/v6 metrics unchanged vs HEAD.

### SDE 2026-10-15 morning: SYS-161 re-run
- arcs-v6 (10-11): $0.1064, 4 arcs, 0 refusals; Polri in Sekilas, not an arc. Offline: v5 Polri claim passed on "Total ada 199" (2 of 24 articles) -> bare total dropped from `_TOTAL_OR_CHANGE`; unit 3,321; 6/6 sys161 mutants KILLED. SYS-161 ready-for-qa.

### QA audit 2026-10-15 (arc-guard rework, 3e8b90c/89eb879)
- Unit 3,320 pass; QA file `scripts/experiments/qa_2026_10_15/test_qa_arc_rework.py` 56/60 (4 red = SYS-164 send-back + SYS-165); dev mutants 76/76, QA mutants 11/16 by dev suites (5 -> DBT-78). Report: reviews/2026-10-15-qa-report.md

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

## Ops 2026-10-12 08:30: SYS-139 quick relief
- The 07:53 Telegram showed VIVA FAILED (the second kill in a row), 4,198 vectorless chunk rows (528 articles) and STORE DIVERGENT 169. The 169 are VIVA's rejected sitemaps whose vector cleanup was lost with the kills. All one cause: SYS-139 #320.
- **Owner approved:** `.env` `SCHEDULE_SOURCE_TIMEOUTS=MEDIAINDONESIA=1500,KUMPARAN=1800,VIVA=1800`. The first run on it is 2026-10-12 19:00. The code fix (flush before the kill) is still open.

## Ops 2026-10-12 08:05: OPS-49 fixed (Postgres shared memory)
- The 05:30 filter-drift audit failed with "DiskFull: could not resize shared memory segment". That is Docker's default 64 MB `/dev/shm`, not the disk (20% used).
- **Owner approved the fix:**
  - backup `newsaggregator_20261012T010159Z.dump`;
  - `shm_size: 1gb` in `docker/docker-compose.yaml`;
  - container recreated (~40 s), counts identical.
- The audit was re-run: saved 0.95, rejected 0.78, no alerts.
- OPS-49 #321 is `status: ready-for-qa`.

## Senior-engineer audit 2026-10-12 (code quality, c69d34d..f7f8672)
- Unit 2,770 passed. Filed: SYS-140 #322 (P2, follow-up's earlier questions' first words become required name anchors), SYS-141 #323 (P3, similarity reads vs_l2 twice under reload; stale docstring), SYS-142 #324 (P3, overlap tail window), DBT-67 #325 (repair scripts import each other's privates). Report: reviews/2026-10-12-senior-code-quality-audit.md

## Dev 2026-10-12: QA + senior-engineer list (spec specs/2026-10-12-qa-senior-fixes-design.md)
Owner decisions: SYS-139 soft deadline only (ADR-011); SYS-104/140 LLM rewrite of follow-ups (ADR-010); SYS-137 delete queued stale chunks (prod write approved); SYS-138/112 soft week window + relevance gate (ADR-012).
- [x] SYS-111 #287 deadline resolved once (2ffdf28, ready-for-qa)
- [x] SYS-139 #320 soft deadline (84781b2, ready-for-qa; needs 3 scheduled VIVA runs)
- [x] SYS-104 #274 + SYS-140 #322 follow-up rewrite (f842ae7, ready-for-qa; restart :8000)
- [x] SYS-141 #323 (e12e8e9), DBT-66 #319 + DBT-65 #318 (4392b9f): ready-for-qa
- [x] SYS-137 #316 store check + drop script + prod write DONE 12:15-12:24 WIB (8b224ec, 7c1fdef): ready-for-qa
- [x] SYS-138 #317 week window (62296a2): ready-for-qa. SYS-112 #289 measured, not recency: back to QA/owner
- [x] SYS-142 #324 measured (5.5% tails); fix timing = owner decision
- [ ] DBT-67 #325 blocked on QA closing SYS-111 (include drop_oversized_queued_chunks.py)

## QA 2026-10-12 (second pass, afternoon): the dev's fixes verified on QA's own tests + held-out questions
Report: reviews/2026-10-12-qa-report-2.md; decisions/qa/qa-pass-2026-10-12b.md.
- **Suites:** unit 2871/5 skipped; integration 214/1 skipped.
- **Mutants:** 38/42 KILLED on the full unit suite. Every survivor is killed by QA's tests or ticketed.
- **Closed (8):** SYS-111, SYS-104, SYS-140, SYS-141, SYS-137, DBT-65, DBT-66, OPS-49.
- **Sent back:** SYS-138. On a thin week, the window leads with an off-topic card (2/10 held-out week questions: Danantara, Harvey Moeis), and Garuda loses on-topic cards.
- **Held:** SYS-139, its unit part verified with a real-worker kill test. It waits for 3 VIVA runs (19:00 tonight first).
- **Filed (P3):** SYS-143 #326, SYS-144 #327, SYS-145 #328, DBT-68 #329, DBT-69 #330.
- **DBT-67 #325 is unblocked** (SYS-111 closed).
- **Security:** no blocker (reviews/2026-10-12-security-review-2.md).

## Dev 2026-10-12 evening: QA second-pass list (spec: specs/2026-10-12-qa-second-pass-fixes-design.md, ADR-013/014/015)
Design approved by the owner. Order:
- [x] SYS-144 #327 -nya adverbs
- [x] SYS-143 #326 refusal/list check
- [x] SYS-145 #328 kept-thread (ADR-014)
- [x] SYS-138 #317 subject gate (ADR-013)
- [x] DBT-69 #330 three tests
- [x] DBT-68 #329 duplicate class + hygiene test
- [x] DBT-67 #325 store_repair module (ADR-015)
- [x] Live re-measurement, EXPERIMENTS.md, ticket evidence
- 6 are `status: ready-for-qa`; DBT-67 waits for 11 of its 13 mutants (run stopped by the host for low memory). The :8000 app was restarted at 20:40 after the crawl (live smoke ok). The DBT-67 mutants run after the 21:00 extraction. Commits 3c429a6 (bugs) and the DBT-67 commit. Mutants: 22 of 22 KILLED for the bug list (see the DBT-67 comment for its own run). Owner: restart :8000.

## Recheck 2026-10-12 ~20:50 (SDE, read-only)
- **The 19:00 crawl was not harmed** by the memory pressure from this session's test and mutant runs: 53 of 54 runs `completed`. VIVA full_text was `completed` 19:10-19:33 (no kill; the first of SYS-139's 3 runs, QA's call). Its only note is 52 transient HTTP 502s (cooldown-stamped).
- **Store after VIVA:** `chunks.embedding_id IS NULL` = 0 (VIVA 0); chunk rows of terminal sitemaps without an article = 0.
- **The one failure is INVESTORID's sitemap 404,** on every run since 10-06. That is the open SRC-59 #260, nothing new.
- **The 21:00 extraction started on time.** Recent full runs took 4-5 h, so it ends ~01:00-02:00.
- **The 11 DBT-67 mutants run after it,** or tomorrow before the 07:00 crawl. Then tear down `%TEMP%\mutwt` (junction first).

## Dev 2026-10-12 night: SRC-59, DBT-60, SYS-91 (spec: specs/2026-10-12-src59-dbt60-sys91-design.md; owner approved)
- [x] DBT-60 date rule (ready-for-qa)
- [x] SRC-59 INVESTORID sitemap_post.xml + id-segment placeholder hook (ready-for-qa; QA needs the 07:00 run)
- [x] SYS-91 repair script; NEWS_L1 dry run 88 CNBC 19xx + 4 TRIBUN empty
- [x] SYS-91 `--apply --all-mismatches` 01:30 10-13 (owner moved it up after the extraction finished, and approved the TRIBUN empties): L1 92 + L2 32 rewritten, backup `backups/sys91_ALL_20261012T182959Z`; scan 0 `19xx`/empty; ready-for-qa
- [x] DBT-67: 13/13 mutants KILLED, ready-for-qa

## QA audit 2026-10-13 (~02:45 WIB): dev fixes of QA's second pass + SRC-59/DBT-60/SYS-91
- Suites: unit 2963 / integration 223 (= dev). QA `test_qa_audit.py`: 53 pass, 24 fail (findings).
- Closed: SYS-138, SYS-143, SYS-91 (per-document diff vs `.bak`, 974,375 docs agree with DB), DBT-67, DBT-68, DBT-69.
- Sent back:
  - SYS-144/145: the held-out *-nya* adverbs regress kept topic switches on the served path, Sritex 4/5→1/5;
  - DBT-60: Decimal/numpy/'20260918.0' still become 1970.
- Held: SRC-59 (07:00 run), SYS-139 (1/3 runs, store check OK).
- Filed: SYS-146 #331, DBT-70 #332, SRC-62 #333, DBT-71 #334.
- Mutants: 21/24 unit (1 equivalent, 2 survivors → DBT-71) + 2/2 integration KILLED. Worktree torn down junction-first; venv intact.
- Report: reviews/2026-10-13-qa-report.md

## PM 2026-10-13 (evening): newsletter story arcs (owner: "too pointy, not storytelling, see the past weeks")
- Decision file: decisions/product-manager/newsletter-story-arcs.md. Owner decisions:
  - arcs inside the daily edition;
  - 3-4 deep stories within 5 min;
  - adaptive lookback ≤ 30 days;
  - importance-first selection;
  - look-ahead only when stated;
  - recommended scope;
  - **pure prose, no labels**.
- Research:
  - corpus probe (EXPERIMENTS.md 2026-10-13, `scripts/experiments/probe_story_arcs.py`): L1 vectors find real arcs for 4/6 of 10-12's leads; KB entities fail on concept stories and drift; no cosine floor separates thread from topic;
  - precedents: Axios, Semafor, NYT The Morning, Full Coverage/Particle, Indonesian "Kronologi".
- Next: principal architect (thread finder, arc writer, guards, replay harness, story memory as P1) → ADR → tracker + tickets → SDE. No code written.

## Architect 2026-10-13 (evening): newsletter story arcs designed, ADR-016 accepted, tickets filed
- Design: `decisions/architect/newsletter-story-arcs.md`.
  - In-edition arc stage: `thread_finder` over NEWS_L1 (already in memory at 12:00), then `story_arc` (1 call + retry, the model picks `alur`, code guards numbers/dates/subject/agenda), then a pure-prose render.
  - `NEWSLETTER_ARCS` default 0, so the output is byte-identical to today's.
  - No thread store; `_edition.stories` JSON is P1's input.
- Owner: approved, and chose "replace after the A/B, keep a switch".
- Tickets: tracker #336.
  - P0: SYS-147 #337, SYS-148 #338, SYS-149 #339, SYS-150 #340 (ship gate: arcs win ≥ 4/5 blind days).
  - P1: SYS-151 #341, SYS-152 #342.
- Found: the editor's rule check fell back on 2 of the last 6 days (10-08, 10-12). This is a known design fallback, not filed; SYS-149 rewrites those rules.

## 10x-team 2026-10-13 (~22:00): story arcs re-prioritised after the /deepen review (ADR-017)
- Filed:
  - DBT-72 #344 source_check (fixes SYS-153 #343);
  - DBT-73 #345 ask_json;
  - DBT-74 #346 newsletter-only setup (no NEWS_L2/e5-large at 12:00);
  - DBT-75 #347 plan/build split + typed Story.
- Re-scoped SYS-147..150 (dependencies, EditorPolicy in SYS-149, phone-PDF check in SYS-150); tracker #336 re-ordered.
- Order: DBT-72 → DBT-73 → SYS-147+DBT-74 → SYS-148 → DBT-75 → SYS-149 → SYS-150 (ship gate). P0 ≈ 6-7 dev sessions.
- ADR-017 accepted (amends ADR-016's in-memory premise). Decisions: staff-engineer/ and engineering-manager/newsletter-story-arcs.md.
- Phase: Planning Complete → SDE. No code written.

## SDE 2026-10-13 (night): newsletter story arcs built (tracker #336, ADR-016/017)
- [x] DBT-72 #344 source_check, fixes SYS-153 #343 (223352b): ready-for-qa.
- [x] DBT-73 #345 ask_json (130c1e3, f929ded): ready-for-qa.
- [x] SYS-147 #337 thread finder (d56551c): ready-for-qa.
- [~] DBT-74 #346 newsletter-only composition root (d56551c). Waits for:
  - the old-vs-new comparison, which needs memory headroom;
  - the 2026-10-14 12:00 log.
- [~] SYS-148 #338 arc writer (a26a6a5). Waits for SYS-150's ≥ 90% accepted.
- [x] DBT-75 #347 plan/build/generate + traces (0c4b8b6): ready-for-qa. The typed Story split out as DBT-76 #348 (EM call).
- [x] SYS-149 #339 EditorPolicy + arc stage behind NEWSLETTER_ARCS=0 (c1a8269): ready-for-qa. Owner: confirm "≥ 1 non-finance".
- [~] SYS-150 #340 replay harness (2dae824): the 5-day replay is running; then the owner's blind read.
- Arcs off is byte-identical (8 fixture days; the editor prompt too). The 10-14 12:00 run is today's edition on the new composition root.
- Tests: unit 3,090+; integration 225/1 skipped. Every new mutant killed (see the SDE file).
- **Incident:** a test overwrote `digests/2026-10-03.md`; restored from the pre-QA copy (`decisions/sde/newsletter-story-arcs.md`).
- 2026-10-14 ~00:00: SYS-150 replay 10-08..12 done.
  - Arcs 19/20 (95%), arc editions 755-856 words, 6/6 coverage every day, $0.60 at the peak price.
  - Repetition metric inconclusive (the matching rule; see SYS-151).
  - SYS-148 ready-for-qa.
  - The owner's blind read + hand-check are next (handoff.md).
  - Mutant worktree torn down; venv intact.

## QA 2026-10-14: owner's read of the arc replay -- arcs read as a chronicle
- Measured on the 5 replayed days: 69% of latar sentences date-led; 13/19 latar with ≥ 3 dates.
- Root cause: `story_arc.PROMPT` ("setiap fakta bertanggal", chronicle-style example). Research: `reviews/2026-10-14-arc-writing-research.md`.
- Filed: SYS-154 #349 (bug P2), SYS-155..160 #350..#355. SYS-157/158 land with SYS-154 (the trust bar).
- SYS-150's ship gate now waits on them; `NEWSLETTER_ARCS` stays 0.

## SDE 2026-10-14 (morning): arcs read as stories -- SYS-154..160 ready-for-qa (tracker #336)
- [x] SYS-160 #355: style metrics + `--compare` + `--metrics-from`. Baseline: date-led 72.3%, 14/19 latar ≥ 3 dates, tie 10/17.
- [x] SYS-154 #349 + SYS-155 #350: prompt and narrative example; the timeline shows each item's relative phrase.
- [x] SYS-156 #351 (`style`), SYS-157 #352 (relative time), SYS-158 #353 (ordinals), SYS-159 #354 (tie, word families).
- Final replay (702386c): 18/20 accepted; date-led 7.8%; 0 latar ≥ 3 dates; tied 17/17; $0.60 at peak.
- Unit 3,243 passed; 55 mutants killed.
- [ ] Owner: the 3-way re-read (`digests/preview/arcs-v5/<date>-compare.pdf`) and the blind A/B (`-X/-Y.pdf`, `key.json`). `NEWSLETTER_ARCS` stays 0.
- Still open from before: DBT-74 #346 (12:00 log + old-path comparison), SYS-150 #340 (the owner's A/B).

## QA 2026-10-14 (afternoon): audit of SYS-154..160 (report: reviews/2026-10-14-qa-report.md)
- **Closed:** SYS-155 #350, SYS-156 #351, SYS-159 #354, SYS-160 #355.
- **Sent back:** SYS-157 #352 ("tiga pekan lalu" -> "pekan lalu"); SYS-158 #353 (one-word record key, "N kali berturut-turut", collectives after verbs).
- **Held:** SYS-154 #349, until the owner's 3-way read on arcs-v5.
- **Filed:** SYS-161 #356 (P2 Polri running total), SYS-162 #357, SYS-163 #358, SYS-164 #359, DBT-77 #360.
- **Evidence:**
  - unit 3243 passed;
  - QA mutants 32/34 KILLED (1 equivalent, 1 -> DBT-77);
  - gates reproduced: 7.8% date-led, 0 with >= 3 dates, 17/17 tied, 18/20 accepted.
- **Next:**
  - SDE: SYS-157/158 rework, SYS-161, then the P3s;
  - owner: 3-way read + blind A/B on arcs-v5. `NEWSLETTER_ARCS` stays 0.

## SDE 2026-10-15 (early morning): QA rework of the arc guards
- [x] Ready for QA: SYS-157 #352, SYS-158 #353 (both reworked), SYS-162 #357, SYS-163 #358, SYS-164 #359, DBT-77 #360. Commits 3e8b90c, 89eb879.
- [~] SYS-161 #356: guard + prompt + tests + 5 mutants done; the 10-11 re-run is held until the SumoPod top-up (balance ~$0-2; the 12:00 newsletter depends on it).
- Tests: unit 3,320 passed; QA's arc file 83/84 (one fixture issue, explained on #353); 76/76 arc mutants KILLED.
- Ops: `KNOWLEDGE_DAILY_COST_LIMIT_USD` set 8 -> 1.5 in `.env` (owner decision for 10-15).
