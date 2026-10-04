# Project Status

## Project: NewsAggregator
**Current Phase:** Implementation (dev): P1/P2 fixes + newsletter. Design approved by owner choice of DeepSeek; spec + ADR-001 written.
**Last Updated:** 2026-10-04 by 10x-team (sde)
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
