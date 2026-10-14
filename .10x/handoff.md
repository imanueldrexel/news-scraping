# Current Handoff

## From: SDE (rework of QA's arc tickets) -> To: QA (verify), owner (top-up, then the arcs-v5 read)
**Date:** 2026-10-15 (early morning)
**Read first:**
- each ticket's dev comment (#352, #353, #356..#360);
- `.10x/decisions/sde/newsletter-story-arcs.md`, section "2026-10-15";
- `.10x/decisions/architect/newsletter-story-arcs.md`, section "2026-10-15" (the dev's calls);
- EXPERIMENTS.md "2026-10-15 — Arc guards rework".

### Ready for QA (`status: ready-for-qa`)
- SYS-157 #352, SYS-158 #353 (both reworked), SYS-162 #357, SYS-163 #358, SYS-164 #359, DBT-77 #360.
- Commits: 3e8b90c (code + tests), 89eb879 (mutant registry + EXPERIMENTS).

### What to verify
- **QA's file:** `scripts/experiments/qa_2026_10_14/test_qa_arcs_story.py` is 83/84.
  - The red one is `TestSys158InParse::test_a_collective_after_a_verb_does_not_cost_a_retry`.
  - It is refused as `subject` on its own fixture: article [1] names neither "Istana" nor "Negara".
  - The `number` part SYS-158 owned is gone (before/after detail on #353). QA's call.
- **Mutants:**
  - The registry's `sys156..164_*`, `sys157r_*`, `sys158r_*` and `qa_metric_ge2_dates` are 76, all KILLED in a scratch copy. Use `QA_MUTANT_TESTS` = the four arc suites + `test_newsletter_arcs.py`.
  - In `qa_mutants_1014.py`, 4 patterns no longer match. Equivalents are named on #352/#359:
    - `qa_tie_ignores_date_opening` → `sys159_date_opening_ties`;
    - `qa_dua_pekan_lalu_any` → `sys157r_weeks_any_slack`;
    - `qa_n_hari_no_slack` → `sys157r_days_no_slack`;
    - `qa_relative_dates_not_blanked` → `_blank_dates` (still equivalent).
- **Judgement calls to check:**
  - SYS-163 drops the repeated agenda rather than refusing;
  - SYS-164's openings cap counts relative-time openings too;
  - SYS-161 runs on every prose field;
  - SYS-158's me-/di-/ber- verb rule with its noun list (it leans to collective on purpose).
- **SYS-164 numbers on v5:** time-led 11/51, ≥ 3 anchors 1/17. QA's 8/51 and 3/17 reproduce under QA's definition, which counts "sejak …" frames; the reconciliation is on #359.
- **Not yet for QA:** SYS-161 #356 waits on its 10-11 re-run.

### Owner
1. **Top up SumoPod.** The balance is about $0-2: $20.25 logged since the 10-12 top-up, plus ~$1.68 of unlogged replays. The extraction cap is now 1.5 (`.env`, as decided for 10-15).
2. After the top-up, SDE runs `replay_story_arcs.py --dates 2026-10-11 --out-dir digests/preview/arcs-v6` (~$0.15). That closes SYS-161's Done-when and shows whether the retry repairs the 2 v5 arcs SYS-164 now refuses on the first try (Karhutla 10-11, Lobster 10-12).
3. The arcs-v5 read (3-way compare + blind A/B) is unchanged. `NEWSLETTER_ARCS` stays 0.

### Still open from before
- DBT-74 #346 (12:00 log + old-path comparison).
- SYS-150 #340 (owner's A/B).

---

## Previous (superseded)

## From: QA (audit of SYS-154..160) -> To: SDE (rework + new tickets), owner (read arcs-v5)
**Date:** 2026-10-14 (afternoon)
**Read first:**
- `.10x/reviews/2026-10-14-qa-report.md`;
- the QA comments on #349..#355;
- `scripts/experiments/qa_2026_10_14/test_qa_arcs_story.py`. Each red test there is a send-back or a ticket.

### SDE, in this order
1. **SYS-158 #353 (sent back)**, `source_check.ordinal_claims`:
   - the record key holds the whole time phrase, not one word;
   - "N kali berturut-turut/beruntun" is read as a series;
   - a word ordinal after a verb (me-/di-/ber-), or in "kedua belah pihak", is collective.
   - Done when QA's TestSys158* pass.
2. **SYS-157 #352 (sent back)**, `relative_times`: "N pekan lalu" / "N bulan lalu" (N > the table's) is read with its own span, or not at all, never as "pekan lalu"/"bulan lalu".
3. **SYS-161 #356 (P2):** "Kini ... bertambah menjadi N" needs a source sentence with N and a change/total word. Prompt rule too. Re-run 10-11.
4. **SYS-162 #357:** a relative phrase is licensed as stated only by today's `terkait` articles.
5. **SYS-164 #359:** time anchors = calendar dates + non-"sejak" relative phrases, in the tie, the caps and the metric, plus the "Pada tanggal/hari" openings.
6. **SYS-163 #358** (agenda repeating latar) and **DBT-77 #360** (a 2-date fixture).

Mutants: `scripts/experiments/qa_2026_10_14/qa_mutants_1014.py <copy>`. Run it in a `git archive` copy; it takes `QA_MUTANT_TESTS`.

### Owner
- The read goes ahead now, on `digests/preview/arcs-v5/`: the 3-way `*-compare.pdf` for 10-11 and 10-12, then the blind A/B and `handcheck.csv`.
- **One known wrong fact:** the Polri arc (10-11) calls 199 a running total after 88. It was a separate telegram (SYS-161).
- **Worth judging in `same_thread`:**
  - IWIP's internship/PPh 21 item;
  - RI-Mesir's IEU-CEPA and "investasi" items.
- `NEWSLETTER_ARCS` stays 0 until the read passes and SYS-157/158/161 are done.

### Still open from before
- DBT-74 #346: the 12:00 log + the old-path comparison.
- SYS-150 #340: the owner's A/B.

---

## Previous (superseded)

## From: SDE (arcs read as stories, SYS-154..160) -> To: QA (verify), owner (3-way re-read + blind A/B)
**Date:** 2026-10-14 (~09:30 WIB)
**Read first:**
- `.10x/decisions/sde/newsletter-story-arcs.md`, section "2026-10-14 (morning)";
- each ticket's dev comment (#349..#355);
- EXPERIMENTS.md: "SYS-160: the arcs' reads-as-a-story metrics" and "re-runs of the arc replay".

### Ready for QA (all `status: ready-for-qa`)
- SYS-154 #349, SYS-155 #350, SYS-156 #351, SYS-157 #352, SYS-158 #353, SYS-159 #354, SYS-160 #355.
- Commits fec04c3, 841992e, dcca96a, 1e56720, 702386c (+ 0d25928 experiments).

### What to verify
- **Gates (final replay on 702386c, `digests/preview/arcs-v5/metrics.json`):**
  - accepted 18/20 (90%, at the gate);
  - date-led 7.8% (≤ 25%);
  - latar with ≥ 3 dates 0 (≤ 2);
  - tied 17/17 (≥ 90%).
- **Baseline:** `replay_story_arcs.py --metrics-from digests/preview/arcs` gives 72.3% / 14 / 10-of-17. It is 2 above the hand count of 45/65 (it also counts "Sebelumnya, pada 19/9", and today's date).
- **Mutants:** `QA_MUTANT_TESTS="tests/unit/test_story_arc.py tests/unit/test_source_check.py tests/unit/test_arc_style.py tests/unit/test_replay_story_arcs.py tests/unit/test_newsletter_arcs.py"`; names `sys154..160_*` and `sys148_*` (55, all KILLED here). Run them in a worktree at a short path.
- **Deviations to judge** (each on its ticket):
  - SYS-159's tie is not "event word only": that rule refused the research's own rewrite;
  - SYS-156 counts sentences that *open* on a date, and its detail rides with numbers/dates/length;
  - SYS-158 covers "terendah/tertinggi sejak" too.
- **Hand-check:** the 10-11 Polri arc ends "Kini jumlah personel yang dimutasi bertambah menjadi 199 orang", reading this wave's 199 as a running total. No guard catches a cumulative misreading. QA's call to ticket.
- **Weak spot:** both fallbacks are market stories with a number the model made up (correctly refused). Price stories with a timeline sit closest to the 90% line.

### Owner
1. **3-way re-read on the phone:** `digests/preview/arcs-v5/2026-10-11-compare.pdf` and `2026-10-12-compare.pdf` (the other 3 days too, if you like). Each arc story appears as Versi A/B/C: new arc, old arc, today's summary. Note which you prefer, then open `compare_key.json`.
2. **Blind A/B** (the SYS-150 ship gate, unchanged): `digests/preview/arcs-v5/<date>-X.pdf` vs `-Y.pdf` for 10-08..12, then `key.json`. Arcs ship if they win ≥ 4/5.
3. **`handcheck.csv`:**
   - `reads_as_story` y/n per arc (new, `kind=arc`);
   - `same_thread` per timeline item;
   - `attributed` per causal sentence.
4. `NEWSLETTER_ARCS` stays 0 until 1-2 pass.

### Still open from before
- DBT-74 #346: the 12:00 log + the old-path comparison.
- SYS-150 #340: the owner's A/B (now on arcs-v5).

---

## Previous (superseded)

## From: QA (owner's read of the arc replay) -> To: SDE
**Date:** 2026-10-14
**Read first:**
- `.10x/reviews/2026-10-14-arc-writing-research.md` (principles, before/after rewrites, changes A-G);
- `.10x/decisions/qa/newsletter-story-arcs.md`.

### Build order
1. **SYS-160 #355 first:** the replay metrics, computed on the existing `digests/preview/arcs/` run as the baseline (date-led 69%, ≥ 3 dates in 13/19).
2. **SYS-154 #349 + SYS-155 #350:** the prompt rewrite and the narrative example, **together with SYS-157 #352** (relative time) **and SYS-158 #353** (ordinals).
3. **SYS-156 #351** (`style` refusal) and **SYS-159 #354** (continuity).
4. **Re-run** `replay_story_arcs.py` on 10-11 + 10-12 (~$0.25 at peak) with `--compare` for the owner's 3-way read; then the full 5 days for the A/B.

### Still open from the SDE handoff below
- DBT-74 #346: the 12:00 log, plus the old-path comparison.
- SYS-150 #340: the owner's A/B, now after the fixes above.

---

## Previous (superseded)

## From: SDE (newsletter story arcs, tracker #336) -> To: QA (verify), owner (blind read + 2 decisions)
**Date:** 2026-10-14 (~00:00 WIB)
**Read first:**
- `.10x/decisions/sde/newsletter-story-arcs.md` (what was built, deviations, evidence, incident);
- each ticket's dev comment;
- EXPERIMENTS.md, the 2026-10-13/14 entries (DBT-72, DBT-73, SYS-147/DBT-74, DBT-75/SYS-149, SYS-150).

### Ready for QA
- DBT-72 #344 (+ SYS-153 #343);
- DBT-73 #345;
- SYS-147 #337;
- SYS-148 #338;
- DBT-75 #347;
- SYS-149 #339.

### Not yet ready
- **DBT-74 #346:**
  - the old-vs-new digest comparison (`scripts/experiments/probe_newsletter_setup.py --path old`) needs ~10 GB free; the host had 8 GB tonight;
  - QA needs the **2026-10-14 12:00 log**: it must show no NEWS_L2 or e5-large load, with the same crawl_log row and Telegram line.
- **SYS-150 #340:** the replay is done. The owner's blind read is next (below).

### Owner
1. **Read the blind pairs** on the phone: `digests/preview/arcs/<date>-X.pdf` and `-Y.pdf` for 2026-10-08..12. Note which one you would rather read each day, then open `key.json`. Arcs ship if they win ≥ 4/5.
2. **Fill `digests/preview/arcs/handcheck.csv`:**
   - `same_thread` y/n for 52 timeline items;
   - `attributed` for 5 causal sentences (one is pre-flagged).
3. **Confirm "≥ 1 non-finance in 3-4 slots"** (SYS-149, `POLICY_ARCS`).
4. **On a pass:** `NEWSLETTER_ARCS=1` in `.env`. The next 12:00 run delivers arcs; the switch back is `0`.

### For QA, notes
- **Mutants:** run in a scratch worktree (`%TEMP%\mutwt`, torn down junction-first tonight, venv verified). `QA_MUTANT_TESTS` per ticket is in the registry comments.
- **Registry:** 24 older mutants elsewhere no longer match their files (crawl/ops/RAG). Not from this work; QA's call to ticket.
- **Restored file:** `digests/2026-10-03.md` was overwritten by a test and restored from the pre-QA copy (possibly not the last production write). See the SDE file.
- **Production:** the 12:00 run on 2026-10-14 is today's edition, byte for byte (arcs off), built on DBT-74's composition root.

---

## Previous (superseded)

## From: 10x-team (EM + Staff Engineer: story arcs re-prioritised) -> To: SDE
**Date:** 2026-10-13 (~22:00 WIB)
**Read first:**
- `.10x/decisions/engineering-manager/newsletter-story-arcs.md` (sequence, gates);
- `.10x/decisions/staff-engineer/newsletter-story-arcs.md` (rules, reuse map);
- ADR-016 + ADR-017;
- the "Re-scope 2026-10-13" section at the bottom of each SYS ticket;
- `memory/HANDOVER-2026-10-13-2137.md`.

### Start here
1. **DBT-72 #344, `core/source_check.py`:** move the guards from `story_summary.py:170-256`, add `dates_in` (fixes SYS-153 #343), and migrate the summary, editor and `web/answer.py`. Gate: guard tests and retargeted mutants green; replay ±2 pts.
2. **DBT-73 #345, `core/llm_json.ask_json`.**
3. **SYS-147 #337 with DBT-74 #346.** Steps 1-2 and 3 can run in parallel.
4. **SYS-148 #338.**
5. **DBT-75 #347.**
6. **SYS-149 #339 (+ EditorPolicy).**
7. **SYS-150 #340:** the owner's blind A/B is the ship gate.

### Rules
- Issue-first for any bug found.
- `Refs #N`.
- Each ticket goes to `status: ready-for-qa` with evidence; dev never closes.
- Pure moves must be byte-identical on a fixture day.
- EXPERIMENTS.md for every replay and measurement.
- Run mutants outside 07:00/19:00/21:00.
- No production DB writes.

### Owner
- Confirm "≥ 1 non-finance in 3-4 slots" (SYS-149).
- Read the 5 blind pairs when SYS-150 is ready.

---

## Previous (superseded)

## From: Principal Architect (/deepen review of the newsletter path) -> To: 10x-team (re-scope tickets, re-prioritise), then SDE
**Date:** 2026-10-13 (~21:40 WIB)
**Read first:** `memory/HANDOVER-2026-10-13-2137.md`, its table "/deepen findings → what the 10x-team should change".

### Asked of the 10x-team
- File DBT tickets:
  - `core/source_check.py` (it absorbs SYS-153 #343);
  - `core/llm_json.ask_json`;
  - the plan/build split of the generator;
  - a newsletter-only setup for the 12:00 job.
- Edit:
  - SYS-148 #338: depends on source_check + ask_json;
  - SYS-149 #339: + EditorPolicy (+ optional Story dataclass);
  - SYS-150 #340: depends on plan/build; + a phone-PDF page-break check;
  - SYS-147 #337: + a link to the setup ticket.
- Re-order tracker #336:
  1. source_check;
  2. ask_json;
  3. SYS-147 + setup;
  4. SYS-148;
  5. plan/build;
  6. SYS-149;
  7. SYS-150;
  8. P1 SYS-151/152.
- Amend ADR-016's consequences (NEWS_L1 loaded explicitly by the newsletter-only setup); update the CLAUDE.md ID map and status.md; hand off to SDE.
- The previous handoff (Architect → SDE, below) still holds for everything not changed here.

---

## Previous (superseded)

## From: Principal Architect (newsletter story arcs) -> To: SDE (build P0), owner (the A/B)
**Date:** 2026-10-13 (~22:00 WIB)
**Read first:**
- `.10x/decisions/architect/newsletter-story-arcs.md`;
- `.10x/adrs/016-story-arcs-in-edition-over-news-l1.md`;
- `.10x/decisions/product-manager/newsletter-story-arcs.md` (copy, the arc prompt, success criteria);
- EXPERIMENTS.md "2026-10-13 — Newsletter story arcs".

### Build order (tracker #336)
1. **SYS-147 #337, thread finder:**
   - `core/thread_finder.py` (pure; `search`/`lookup` injected);
   - `SQLAlchemyNewsletterDataSource.get_timeline_rows`;
   - the vs_l1 adapter.
2. **SYS-148 #338, arc writer:** `core/story_arc.py`, with the PM prompt verbatim and guards for number / date / subject / alur / agenda / empty history.
3. **SYS-149 #339, edition stage:**
   - behind `NEWSLETTER_ARCS` (default 0, byte-identical);
   - 3-4 picks and ≥ 1 non-finance (a scaled default: confirm with the owner);
   - pure-prose render, budget, `_edition.arcs` / `_edition.stories`, generator wiring.
4. **SYS-150 #340, replay harness:** `replay_story_arcs.py`, blind X/Y on 10-08..10-12, `handcheck.csv`, metrics. **This is the ship gate.**
5. **P1, only after SYS-150's numbers:** SYS-151 #341 story memory (if repetition > 30%); SYS-152 #342 causal check (P0 if the hand-check finds an unattributed cause).

### Owner
- Read 5 blind pairs on the phone when SYS-150 is ready. Ship if arcs win ≥ 4/5.
- On a pass, set `NEWSLETTER_ARCS=1` in `.env` (owner-chosen rollout: replace, keep the switch).

### Notes
- NEWS_L1 is already in memory in the 12:00 job (`init_crawler`, 1.4 s load). The search is read-only: no run lock, no save.
- Reuse `story_summary.unsupported_number`, `_date_in`, `off_subject` and `story_words`; do not fork them.
- Issue-first holds for any bug found while building. Commit footers use `Refs #N`; dev leaves tickets `status: ready-for-qa`.

---

## Previous (superseded)

## From: PM (newsletter story arcs) -> To: Principal Architect
**Date:** 2026-10-13 (~21:30 WIB)
**Read first:** `.10x/decisions/product-manager/newsletter-story-arcs.md` (requirements, P0/P1, success criteria, copy, the draft arc prompt); EXPERIMENTS.md "2026-10-13 — Newsletter story arcs"; `scripts/experiments/probe_story_arcs.py`.

### Asked of the architect
- **Design the P0:**
  - thread finder: NEWS_L1, 30 days, a wide floor, one item per day;
  - arc writer: a second LLM call for the edition's top 3-4 stories, through the shared Summarizer;
  - guards extending `story_summary`'s:
    - numbers ⊆ today ∪ the chosen `alur`;
    - prose dates ⊆ the dates of the `alur` items;
    - an `alur` subject check;
    - `agenda` traceable;
  - the pure-prose render in `newsletter_edition`/`newsletter_copy`;
  - a replay harness for the owner's blind A/B on 5 days (10-08..10-12 included, for repetition).
- **Decide where the history comes from:** raw past articles (DB headline + L1 opening) vs past delivered stories. The latter is P1 story memory: does it need a table now so P1 is not a rewrite?
- **Load-cost question:** the newsletter does not load NEWS_L1 today. It uses MiniLM on L1 texts. NEWS_L1 is 712 MB on disk; the 12:00 job's memory and run-lock interaction (OPS-26/SYS-53: read-only, so no lock) need checking.
- **Write:** an ADR, then the build order for tickets (issue-first; `Refs #N`).

### Constraints
- Edition ≤ 1,200 words; newsletter ≤ $0.05/day; every reader string in `core/newsletter_copy.py`.
- The full archive digest is unchanged. #315 entity links stay parked: entities are not P0.

---

## Previous (superseded)

## From: QA (audit of the dev's fixes of QA's second pass + SRC-59/DBT-60/SYS-91) -> To: SDE (3 send-backs, 5 new tickets), owner (1 choice)
**Date:** 2026-10-13 (~02:45 WIB)
**Read first:**
- `.10x/reviews/2026-10-13-qa-report.md`;
- `.10x/decisions/qa/qa-pass-2026-10-13.md`;
- EXPERIMENTS.md "2026-10-13 — QA audit …";
- the QA comment on each ticket.

QA's tests and probes: `scripts/experiments/qa_2026_10_13/` (`test_qa_audit.py`: 53 pass / 24 fail by design; `probe_qa_heldout.py`).

### Verdicts
- **Closed (6):** SYS-138, SYS-143, SYS-91, DBT-67, DBT-68, DBT-69.
- **Sent back (3):** SYS-144, SYS-145, DBT-60.
- **Held:**
  - SRC-59: the 07:00 10-13 run;
  - SYS-139: run 1 of 3 completed and the store is clean;
  - still held from earlier: SYS-79, SYS-82/83, OPS-42, SYS-40.

### For SDE, in order
1. **SYS-144 #327 + SYS-145 #328 (one fix).** Six common *-nya* adverbs are not on the list (*sebaiknya, sebetulnya, nantinya, sayangnya, secepatnya, sepenuhnya*). Through `kept-thread`, a kept topic switch is pulled to the old thread on the **served** path:
   - Sritex: 4/5 → 1/5;
   - Waskita Karya: 5/5 → 2/5.

   Suggested: a structural rule (e.g. a follow-up that names its own subject is not pulled to the thread), not only a longer list. Measure on `probe_qa_heldout.py B` plus the Fed pair.
2. **DBT-60 #258:** these still become 1970: `Decimal`, `numpy.int64`, `'20260918.0'`, `'+20260918'`. `'1695000000.0'` is accepted as Unix seconds. Repro: `test_qa_audit.py::TestDbt60NumericForms`.
3. **SYS-146 #331 (P3 web):** "Apa itu Danantara dan siapa pemimpinnya?" 0/5 (`fts=0`). A *-nya* filler word becomes the heaviest required anchor.
4. **DBT-71 #334:** 2 surviving mutants: SRC-59's `<title>` whitespace collapse, DBT-68's async shadow check.
5. **DBT-70 #332:** `check_store_consistency` imports `repair_store_consistency._load_state`.
6. **SRC-62 #333 (P3 scraper):** INVESTORID `money-lab` is filed as `news` (`re.sub` + `\w+`); decide the section from 3 titles.

### Owner
- :8000 serves 3c429a6, so the SYS-145 regression is live for follow-ups whose topic switch holds an unlisted adverb. QA recommends leaving it until the fix: it is rare, and the Fed-style follow-ups it fixes are common. The alternative is to ask dev to revert ADR-014's branch now.
- :8000 also holds the pre-SYS-91 FAISS metadata until it restarts (no reader impact).

### For QA next
- SRC-59 after 07:00: INVESTORID sitemap row `completed` with new rows; after full_text, headline = og:title.
- SYS-139 runs 2-3 (07:00, 19:00 10-13).

---

## Previous (superseded)

## From: SDE (SRC-59, DBT-60, SYS-91; DBT-67 finished) -> To: QA, owner
**Date:** 2026-10-12 (~23:00 WIB); updated 2026-10-13 01:35
**Read first:** `.10x/decisions/sde/open-p2-p3-2026-10-12.md`; `.10x/specs/2026-10-12-src59-dbt60-sys91-design.md`; EXPERIMENTS.md "SRC-59 INVESTORID probe…"; the ticket comments.

### Ready for QA
- **DBT-67 #325:** all 13 mutants KILLED.
- **DBT-60 #258.**
- **SRC-59 #260:** the scheduled-run evidence is the 07:00 10-13 run (INVESTORID sitemap row `completed`, new rows, og:title headlines after full_text).
- **SYS-91 #257:** applied 01:30 10-13 with `--all-mismatches` (owner-approved: moved up from 06:00, TRIBUN empties included). L1 92 + L2 32 rewritten; backup `backups/sys91_ALL_20261012T182959Z` (4.2 GB, the rollback); a fresh scan finds 0 `19xx`/empty in either index. :8000 still holds the pre-repair metadata until it restarts (display uses DB dates).
- Plus the earlier six: SYS-138/143/144/145, DBT-68/69.

---

## Previous (superseded)

## From: SDE (principal; QA's second-pass list) -> To: QA (verify, close), owner (restart :8000)
**Date:** 2026-10-12 (night)
**Read first:**
- `.10x/decisions/sde/qa-second-pass-fixes-2026-10-12.md`;
- ADR-013 (week-window subject gate), ADR-014 (kept-thread), ADR-015 (store_repair module);
- EXPERIMENTS.md "2026-10-12 — SYS-138 rework (ADR-013) and SYS-143/144/145 (ADR-014)";
- the evidence comment on each ticket.

### Ready for QA (`status: ready-for-qa`)
- **SYS-138 #317 (reworked):**
  - a this-week article leads only if it holds the question's subject (names, else anchors);
  - `probe_week_window_lead.py`: 0/10 keywordless card-1 leads; KPK/IHSG 5/5 this week;
  - your Danantara repro test has a fixture defect (explained on the ticket); the corrected shape is in `tests/unit`.
- **SYS-143 #326:** refusal and list-item check.
- **SYS-144 #327:** 22 `-nya` adverbs; your 3 pairs' fallback = Alone.
- **SYS-145 #328:** `kept-thread`; the Fed pair 5/5 on a forced-kept probe; switch pairs unchanged.
- **DBT-69 #330:** your 3 mutants KILLED.
- **DBT-68 #329:** hygiene test; mutant KILLED.
- **DBT-67 #325 (code done, c02470a, NOT yet labelled):** store_repair module. The host stopped its mutation run for low memory after 2 of 13 mutants (both KILLED); the label goes on once the other 11 are run. Your first-pass `qa_2026_10_12/test_qa_tickets.py::TestSys111DeadlineResolvedOnce` patches names that DBT-67 renamed (see the ticket).

### Owner
- :8000 restarted 2026-10-12 20:40 after the 19:00 crawl (on 3c429a6/c02470a). Live smoke: "Apa kabar Danantara pekan ini?" gives card 1 = 8 Oct "Deviden Danantara…", `window=7d+1`, no Primbon card, answer ok. No production DB or FAISS write was made.
- Unchanged from QA's handoff: `.env` VIVA=1800 stays until QA closes SYS-139.

### For QA next
- SYS-139: the three scheduled VIVA runs (unchanged).
- Re-verify SYS-138 on questions neither of us wrote.

---

## Previous (superseded)

## From: Architect/EM/Senior (planning of QA's second-pass list) -> To: SDE (same session)
**Date:** 2026-10-12 (evening)
**Read first:** `.10x/specs/2026-10-12-qa-second-pass-fixes-design.md`; ADR-013 (week-window subject gate), ADR-014 (kept-thread), ADR-015 (store_repair module); `.10x/decisions/senior-engineer/qa-second-pass-fixes-2026-10-12.md`.
Order: SYS-144 -> SYS-143 -> SYS-145 -> SYS-138 -> DBT-69 -> DBT-68 -> DBT-67 -> live measurement.
QA's Danantara repro test has a fixture defect (its older hit's keyword_score is overwritten to 0 by the `_coverage` stub): explain on SYS-138, write a correct test in `tests/unit`.

---

## Previous (superseded)

## From: QA (second pass of the 2026-10-12 list) -> To: SDE (1 send-back, 5 new P3s, DBT-67 unblocked), owner (1 choice)
**Date:** 2026-10-12 (~15:30 WIB)
**Read first:**
- `.10x/reviews/2026-10-12-qa-report-2.md`;
- `.10x/decisions/qa/qa-pass-2026-10-12b.md`;
- EXPERIMENTS.md "2026-10-12 — QA (second pass) …";
- the QA comment on each ticket.

QA's tests and probes: `scripts/experiments/qa_2026_10_12b/`.

### Verdicts
- **Closed (8):** SYS-111, SYS-104, SYS-140, SYS-141, SYS-137, DBT-65, DBT-66, OPS-49.
- **Sent back:** SYS-138 #317.
- **Held:** SYS-139 #320 (3 scheduled VIVA runs). Still held from earlier: SYS-79, SYS-82/83, OPS-42, SYS-40.

### For SDE, in order
1. **SYS-138 #317 (sent back).** The week window leads with any this-week hit over the floor:
   - "Apa kabar Danantara pekan ini?" → card 1 is a Primbon piece (keyword coverage 0);
   - Harvey Moeis → card 1 is a Pemko Medan piece;
   - Garuda loses on-topic cards.

   A window hit must be *relevant* to lead. Measure on `probe_week_window_lead.py` (10 held-out questions) and `probe_recency_tuning.py`.
   - Repro: `test_qa_fixes.py::TestSys138WeekWindow::test_a_keywordless_week_paragraph_does_not_lead_a_relevant_older_one`.
   - Also add tests for picked dates and below-floor week hits (2 mutants survive `tests/unit`).
2. **SYS-143 #326:** `followup.check` passes a refusal (ADR-010 decision 3).
3. **SYS-144 #327:** `-nya` adverbs (sebenarnya, selanjutnya, akhirnya…) are back-references on the fallback. Fix this before SYS-145.
4. **SYS-145 #328:** "Bagaimana dampaknya ke rupiah?" after The Fed is `kept`: 0/5 Fed cards, while the fallback gets 5/5.
5. **DBT-69 #330:** 3 surviving mutants: the drop script's `--source` scope, its 80-word boundary, and an unusable rewrite still counted.
6. **DBT-68 #329:** the duplicate `TestSoftDeadline`, plus a hygiene test.
7. **DBT-67 #325:** unblocked (SYS-111 closed). Include `drop_oversized_queued_chunks.py`.

QA's `test_qa_fixes.py` has 9 expected failures today: SYS-143 ×3, SYS-144 ×5, SYS-138 ×1. They should pass as each lands.

### Owner
- **SYS-138's thin-week lead is live on :8000.** Leave it until the rework, or ask dev to revert the window now. QA recommends leaving it: it only affects week-cue questions, and it helps KPK/IHSG.
- `.env` still has `VIVA=1800` (SYS-139 relief). Remove it after QA closes SYS-139.

### For QA next
- **SYS-139:** VIVA full_text at 19:00 tonight, then 07:00 and 19:00 on 10-13. Each must be `completed` (a `stopped early (SYS-139)` note passes). After a completed run, `embedding_id IS NULL` must be 0 and `l*_no_articles_terminal` 0 (now 1). Check the log for a run whose deadline passed before batch 1 (ADR-011's accepted risk).
- Re-verify SYS-138 when it comes back, on the held-out questions, not the dev's.

---

## Previous (superseded)

## From: SDE (principal; the 2026-10-12 QA + senior list) -> To: QA (verify, close), owner (2 decisions)
**Date:** 2026-10-12 (~12:40 WIB)
**Read first:** `.10x/decisions/sde/qa-senior-fixes-2026-10-12.md`; ADR-010/011/012; EXPERIMENTS.md 2026-10-12 entries; the evidence comment on each ticket.

### Ready for QA (`status: ready-for-qa`)
- **SYS-111 #287 (P1):** QA's own `TestSys111DeadlineResolvedOnce` now passes.
- **SYS-139 #320:** needs the scheduled evidence, 3 consecutive VIVA full_text runs completed (a `stopped early (SYS-139)` note is a pass). The first is 19:00 tonight with `.env` VIVA=1800 still set. NB: `embedding_id IS NULL` and terminal 169 were cleared by SYS-137's write, not by a run (comment on the ticket).
- **SYS-104 #274 + SYS-140 #322:** LLM rewrite (ADR-010). QA's `TestSys104RetrievalText` tests the removed `retrieval_text` and fails by design. Restart :8000.
- **SYS-141 #323, DBT-66 #319, DBT-65 #318.**
- **SYS-137 #316:** production write done and verified (all three oversized/divergence counts 0).
- **SYS-138 #317:** week window (ADR-012).

### Not ready, with evidence
- **SYS-112 #289:** not a recency problem. The "BI" abbreviation (MiniLM) and old high-cosine passing mentions. QA to re-scope or file (abbreviation expansion is a new requirement).
- **SYS-142 #324:** 45,741 overlap tails (5.5% of served L2). Even-window fix proposed. **Owner: change the chunker now, or with the next planned re-chunk?**
- **DBT-67 #325:** waits for QA to close SYS-111; it must include `drop_oversized_queued_chunks.py`.

### Web app restarted 2026-10-12 ~12:47 WIB (owner closed the old one)
- `venv\Scripts\python.exe -m uvicorn newscrawler.web.app:app --port 8000`: health ok, warm-up 17 s, NEWS_L1 117,863 / NEWS_L2 830,333 (the post-SYS-137 counts).
- Live smoke (`/api/query`, 4 questions, $0.0013):
  - KPK minggu ini: `window=7d`, cards 8-11 Oct;
  - OJK -> "Berapa target pertumbuhannya tahun depan?": `rewrite=llm`, credit-growth cards;
  - -> "Apa itu Danantara?": `rewrite=kept`;
  - all answers ok.
- **For QA (dev files no tickets from testing):** Danantara card 4 is JPNN "Petir India" (sitemap 13278, 26 Feb 2026), a Disway opinion column under JPNN's `news` branch. It names Danantara, so it is a keyword-only hit. It is not caused by today's changes (chunked 10-08). It is the SYS-49 opinion-column policy at article level.

### Suites at handoff
- unit 2871 passed / 5 skipped;
- integration: see the SYS-137 comment.
- Mutants this session: 52 registered + 4 integration, all KILLED against green baselines (`%TEMP%\mutwt`, see the path-length trap).

---

## Previous (superseded)

## From: Architect/EM/Senior (planning of the 2026-10-12 QA + senior list) -> To: SDE (same session)
**Date:** 2026-10-12
**Read first:** `.10x/specs/2026-10-12-qa-senior-fixes-design.md`; ADR-010 (follow-up rewrite), ADR-011 (soft deadline), ADR-012 (recency window); `.10x/decisions/senior-engineer/qa-senior-fixes-2026-10-12.md` (approach per ticket).
Order: SYS-111 → SYS-139 → SYS-104+140 → SYS-141, DBT-66, DBT-65 → SYS-137 (prod write at night) → SYS-138+112 → SYS-142 (measure) → DBT-67 (after QA closes SYS-111).

---

## Previous (superseded)

## From: Senior Engineer (code-quality audit of c69d34d..f7f8672) -> To: SDE
**Date:** 2026-10-12
**Read first:** `.10x/reviews/2026-10-12-senior-code-quality-audit.md`; `.10x/decisions/senior-engineer/code-quality-audit-2026-10-12.md` (approach per ticket).

The QA list below still comes first. The audit adds four tickets and places them in that order:
1. SYS-111 #287 (P1, QA send-back): unchanged, first.
2. **SYS-104 #274 + SYS-140 #322 (P2) together.**
   - `keywords.terms` judges a name by position in the joined thread, so `kebijakan` from an earlier question becomes a required anchor.
   - Take the terms per question (`terms(questions)`), follow-up first.
   - Test the composed path.
3. **SYS-141 #323 (P3):** `ChunkFAISSDatasource.similarity`: capture `vs = self.vs_l2` once; fix the `1 - d^2/2` docstring.
4. **DBT-67 #325:** move the shared repair steps to `newscrawler/tools/store_repair.py`, only after SYS-111 closes, with no behaviour change.
5. **SYS-142 #324 (P3):** measure the overlap-tail rows only; any fix rides the next re-chunk.

---

## Previous (superseded)

## From: QA (independent pass of the 2026-10-09 SDE handoff + held tickets) -> To: SDE (2 send-backs, 4 new P3s), owner (SumoPod key)
**Date:** 2026-10-12
**Read first:**
- `.10x/reviews/2026-10-12-qa-report.md`;
- `.10x/decisions/qa/qa-pass-2026-10-12.md`;
- EXPERIMENTS.md "2026-10-12 — QA of the 2026-10-08/09 retrieval fixes and SYS-109 …";
- the QA comment on each ticket.

### Verdicts
- **Closed (24):**
  - SYS-105..SYS-110, SRC-60/61;
  - DBT-61..64, OPS-46/47;
  - OPS-43, OPS-20, SYS-39, SRC-57, SYS-64, SYS-66, SYS-70, OPS-40, DBT-51/52.
- **Held:**
  - SYS-79 (no real blip in 16 runs);
  - SYS-82/83, OPS-42 (owner reads);
  - SYS-40 (owner + SRC-34).

### For SDE, in order
0. **SYS-139 #320 (P2, new, grows every run).** VIVA's full_text was killed at 1,200 s in its last batch on 10-11 19:00 and 10-12 07:00. 538 saved articles (4,198 chunk rows) have no vectors.
   - **Quick relief APPLIED 2026-10-12** (owner): `.env` `SCHEDULE_SOURCE_TIMEOUTS=MEDIAINDONESIA=1500,KUMPARAN=1800,VIVA=1800`. Remove the VIVA entry when the fix lands.
   - Fix: a soft deadline that flushes before the kill.
1. **SYS-104 #274 (P2, sent back).** A follow-up that names a new subject is retrieved on the old one: 5/5 topic-switch pairs give 0-1 of 5 on-topic cards. The thread's recency cue leaks too.
   - Measure with `scripts/experiments/qa_2026_10_12/probe_topic_switch_followups.py` and the 7 elliptical pairs (`probe_rag_rank_breakdown.py --followups`).
2. **SYS-111 #287 (P1, sent back).** `repair_boilerplate_bodies._apply_locked` calls `parse_until` again after the deletes. Resolve the deadline once.
   - QA's repro: `scripts/experiments/qa_2026_10_12/test_qa_tickets.py::TestSys111DeadlineResolvedOnce`.
3. **SYS-137 #316 (P3).** VIVA's queued June chunks (≤ 450 words) are adopted when the crawl saves those articles. Repairing the queued rows is a production write: owner approval.
4. **SYS-138 #317 (P3)** with SYS-112 #289. Unfiltered "minggu ini" questions get weeks-old articles. Re-tune both on one measurement.
5. **DBT-66 #319 (P3).** 4 untested thresholds (`qa1012_*` mutants).
6. **DBT-65 #318 (P3).** A control character in the OPS-47 trap line; add a hygiene test.

### Owner
- **2026-10-12 update:** topped up to $22.50 and the key works. Backlog clears by 10-15 at the $8 cap. **On 10-15 set `KNOWLEDGE_DAILY_COST_LIMIT_USD=1.5`** (owner: every article, ~$36/month, budget ~$100: `decisions/cto/llm-budget.md`). **A top-up is due by ~10-16** (see status.md, "Ops 2026-10-12").
- **SumoPod (before the top-up):**
  - the account budget ($22.50) ran out on 10-10 at 01:04 and the key has been blocked since 10-11;
  - the 12:00 newsletter (no edition on 10-11), the 21:00 extraction and the search answers are degraded until it is topped up or unblocked;
  - nightly extraction spends ~$5-7 against that balance (~50k articles pending).
- Restart :8000 if not done since 10-09.

### For QA next
- **SYS-79:** the first morning a source blips.
- **SYS-139:** the VIVA kill repeated at 07:00 (1,924 → 4,198 pending rows; 169 terminal sitemaps whose vectors were not removed). On the 1,800 s limit from the 19:00 run, check:
  - VIVA completes;
  - 0 `embedding_id IS NULL` rows;
  - `l*_no_articles_terminal` 0.
- **Re-verify SYS-104 and SYS-111** when they come back.

---

## Previous (superseded)

## From: SDE (SYS-109 built and run on production) -> To: QA (verify, close), owner (restart :8000, SumoPod key)
**Date:** 2026-10-09 (00:50)
**Read first:**
- `.10x/decisions/sde/chunks-fit-encoder-window.md`;
- ADR-008;
- EXPERIMENTS.md "2026-10-08 (evening) — SYS-109" (production results at the end of Result);
- the evidence comment on each ticket.

### Ready for QA (`status: ready-for-qa`)
- **SYS-109 #283:**
  - L2 windows ≤ 80 words; the production re-chunk is done.
  - Re-run `probe_late_recall_live.py --measure scripts/experiments/late_recall_sample_2026-10-08.json` (the sample behind both measurements); expect late @1 0.360, early @1 0.580.
  - Run `check_store_consistency.py` and the SQL `token_count > 80` = 0.
- **DBT-64 #286:** mention indexes on both DBs; integration 210 passed.
- **SYS-111 #287:** `--until` is the next HH:MM; a too-close deadline refuses before deleting. Mutants `sys111_*` (unit) and the guard removals (integration `-k too_close`).
- **OPS-47 #288:**
  - a mutation worktree's teardown (docstring of `qa_mutation_runner.py`);
  - **use it**: `rmdir` the junction before `git worktree remove`;
  - check `pip freeze` == `requirements.txt` after.

### Open, found tonight
- **SYS-112 #289** (P2, web): after the windows, same-day keyword hits clear the 0.55 recency gate. "Menkeu sekarang" leads with Danantara dividend stories; the BI-decision question loses the decision. Confounded by new 8 Oct articles. Re-tune offline on the windowed scores.

### Production state
- NEWS_L2: 750,871 vectors (~1.1 GB `.faiss` + 0.5 GB `.pkl`), ~2x before.
- Rollback: `backups/sys109_ALL_20261008T130410Z` + OPERATIONS.md.
- pg_dump `newsaggregator_20261008T130309Z.dump` was taken before the run.
- The 21:00 extraction on 2026-10-08 exited 2 (run lock held by the re-chunk); the next one is 2026-10-09 21:00.
- The venv was repaired at 00:40; the next scheduled process is the 07:00 crawl.

---

## Previous (superseded)

## From: Architect/EM (SYS-109 design + plan) -> To: SDE (same session: build, then the overnight production re-chunk)
**Date:** 2026-10-08 (evening)
**Read first:** ADR-008; `.10x/specs/2026-10-08-sys109-chunks-fit-encoder-window-design.md`; `.10x/decisions/{architect,dba,senior-engineer,engineering-manager}/chunks-fit-encoder-window.md`.
- Decision: L2 chunks of at most 80 words (overlap 20, min 40), MiniLM unchanged; the store is re-chunked L2-only (L1, mentions untouched); DBT-64 #286 adds the mention indexes first.
- Production: fresh dump -> migration -> `rechunk_stale_chunks.py --all --apply --until 06:15` once the 19:00 crawl releases the lock.

---

## Previous (superseded)

## From: SDE (QA's 2026-10-07 retrieval findings fixed) -> To: QA (verify, close), owner (key, restart :8000)
**Date:** 2026-10-08 (evening)
**Read first:**
- `.10x/decisions/sde/rag-retrieval-quality.md`;
- ADR-007;
- EXPERIMENTS.md, "2026-10-08 — SDE fixes of QA's retrieval findings";
- the evidence comment on each ticket.

### Ready for QA (`status: ready-for-qa`)
- SYS-104 #274, SYS-105 #275, SYS-106 #276, SYS-107 #277, SYS-108 #278;
- SRC-60 #279, SRC-61 #280;
- DBT-61 #281, DBT-62 #282;
- OPS-46 #259 (carried over; same fixture file as DBT-61).
- Found and fixed: SYS-110 #284 (`semantic_score` was not the cosine), DBT-63 #285 (fixture eol in worktrees).
- Found, **not** fixed: SYS-109 #283 (MiniLM sees only ~97 words of a chunk; a full re-embed, owner decision).

### Production writes done today (owner-approved; pg_dump `newsaggregator_20261008T100931Z.dump` first)
- SRC-60 settle (KUMPARAN reader posts);
- SRC-61 KUMPARAN body repair;
- SYS-105 re-chunk of 3,075 articles.

Backups and counts are in the decisions file.

### What to test
- **Suites:** `tests/unit`; `tests/integration` (now safe during a crawl and with no outbox redirect).
- **Mutants** `sys104_*`..`sys110_*`, `src60_*`, `src61_*` and the retargeted `sys100_no_overfetch`, `sys103_*`, `qa1007_*`.
  - **Re-create any old worktree first** (DBT-63, or `git checkout -- tests/fixtures`), then run the unmutated baseline.
  - 11 unrelated mutants were stale at HEAD before this work: `ops32_no_retry`, `ops32_refusal_queued_forever`, `ops33_*` (2), `ops35_*` (2), `sys68_*` (3), `ops20_call_not_counted`, `sys67_prompt_focus_removed`. Yours to ticket.
- **Live, read-only:** `probe_rag_rank_breakdown.py --replay --followups --detail 5`, then hand-check:
  - the BI-Rate top 5 holds no reader post;
  - the gold question's sources are from today.
- **Needs the key:** `replay_rag_answers.py` against a second uvicorn. SYS-107's "the answer cites an article of that day" can only be seen with a working answer.
- **The 19:00 crawl:** KUMPARAN's crawl_log note should read `N URL(s) out of scope: not a kumparan newsroom account (reader post) N`. SRC-57's intake should drop (the live listing kept 142 of 400).

### Owner
- **The SumoPod/DeepSeek key is blocked** (`401 Key is blocked. Update via /key/unblock`, seen 2026-10-08 ~16:30 WIB). The search page shows "Coba lagi"; tonight's 21:00 extraction (which re-extracts 576 KUMPARAN articles) and tomorrow's 12:00 newsletter fail until it is unblocked.
- Restart :8000 (one worker) to serve the new retrieval.

### Risks
- Retrieval is slower than SYS-103: 62-625 ms warm (1.1 s for one follow-up), cold up to 2.1 s.
- Residuals: an unknown name (Purbaya) 3/5; 2 of 7 follow-ups mixed.

---

## Previous (superseded)

## From: QA (independent pass) -> To: SDE (retrieval quality), owner (restart :8000, approvals)
**Date:** 2026-10-07 (evening)
**Read first:**
- `.10x/reviews/2026-10-07-qa-independent-report.md`;
- `.10x/decisions/qa/qa-pass-2026-10-07-rag.md`;
- EXPERIMENTS.md, "2026-10-07 — QA of tracker #272 …".

### Verdicts
- **Closed:** SYS-92..SYS-103, SRC-58.
- **Nothing sent back.**

### For SDE, in order
1. **SYS-105 #275:** skip L2 hits under ~8 words in `retrieve` now; fix the chunker's trailing merge. The repair needs the owner's approval (production FAISS write).
2. **SYS-106 #276:** rank fusion, or a real semantic score for keyword-only hits.
3. **SYS-107 #277:** date tie-break in the FTS; semantic over-fetch.
4. **SYS-104 #274:** carry the thread into follow-up retrieval.
5. **SRC-60 #279:** kumparan reader posts. Skip by URL; the stored-row cleanup needs approval.
6. **P3s:** SYS-108 #278, SRC-61 #280, DBT-61 #281, the `qa1007_*` test gaps.
7. **Carried over:** SRC-59 #260 (P2, INVESTORID 404 on every run), OPS-46 #259 (recurred today: the 12:00 newsletter delivered 10 test alerts).

Measure every retrieval fix with `scripts/experiments/probe_rag_rank_breakdown.py --replay` before and after.

### Owner
- Restart the :8000 web app (one worker): it still runs the pre-redesign code.

### For QA next
- OPS-43: the 10-08 and 10-09 12:00 runs.
- OPS-20/SYS-39: the 10-07 21:00 extraction.
- SRC-57, SYS-64, SYS-66: their run counts.

---

## Previous (superseded)

## From: SDE (SYS-103 built) -> To: QA (verify, close), owner (restart :8000)
**Date:** 2026-10-07
**Read first:** ADR-006; `.10x/decisions/sde/rag-keyword-search.md`; the SYS-103 #273 evidence comment; EXPERIMENTS.md "2026-10-07 — SYS-103 built".

### Ready for QA
SYS-103 (#273), in addition to SYS-92..SYS-102 below.

### What to test
- `tests/unit/test_rag_keywords.py`, `test_query_processor_ranking.py`, `tests/integration/test_rag_keywords_live.py`.
- Mutants `sys103_*` (25), as for #272.
- Live:
  - `replay_rag_answers.py` (now 11 questions; ~$0.0007 each in DeepSeek's peak window);
  - `probe_fts_query_shapes.py --only idf_score` (read-only).
- **Hand-check:**
  - the BI-Rate question's ranks 1-2 (opinion pieces);
  - whether `RAG_MIN_KEYWORD_COVERAGE=0.6` lets junk in on your own questions.

### Known limits
- No stemming or phrase match.
- First-touch latency up to ~1.3 s on cold Postgres pages.

---

## Previous (superseded)

## From: SDE (tracker #272 built) -> To: QA (verify, close), owner (restart :8000)
**Date:** 2026-10-07
**Read first:**
- `.10x/decisions/sde/rag-search-redesign.md`;
- `.10x/reviews/2026-10-07-qa-report.md`;
- ADR-005;
- EXPERIMENTS.md, 2026-10-07.

### Ready for QA (evidence on each ticket)
SYS-92..SYS-102 (#261-#271).

### What to test
- `tests/unit/test_rag_*.py` and `tests/integration/test_rag_filters_live.py`.
- Mutants `sys92_*` .. `sys102_*` in `qa_mutation_runner.py`. Use a worktree, with `QA_MUTANT_TESTS` set to the RAG test files.
- Live, read-only except the usage rows (each question ~$0.0004 under `web:<model>`):
  - `scripts/experiments/replay_rag_answers.py`;
  - `scripts/experiments/e2e_rag_page.py`;
  - `scripts/experiments/snapshot_rag_page.py`.
- Not done by dev: a screen reader, axe.

### Owner
- Restart the web app on :8000 (single worker); it still runs the old code.
- SYS-103 #273 (keyword retrieval) to prioritise.

### Risks
- **The page is unauthenticated.** Keep it on 127.0.0.1; sharing needs auth plus a rate limit (security review).
- **Server memory:** sessions and pending turns live in memory, so a restart between a question's two requests shows "kedaluwarsa".

---

## Previous (superseded)

## From: Architect/EM (design + planning) -> To: SDE (same session), owner (mockup)
**Date:** 2026-10-07
**Read first:** ADR-005; `.10x/decisions/{architect,senior-engineer,engineering-manager}/rag-search-redesign.md`.
- **Provider:** decided by the owner, DeepSeek (`RAG_LLM_PROVIDER=openai`).
- **Build order:**
  1. the mockup (the owner approves);
  2. the copy table;
  3. the summarizer's `complete()`;
  4. answer parsing;
  5. retrieval and filters;
  6. answer states;
  7. routes and turns;
  8. templates and CSS;
  9. the live replay;
  10. docs and tickets.

---

## Previous (superseded)

## From: PM -> To: SDE (next top priority), QA (2026-10-07 scheduled runs, unchanged)
**Date:** 2026-10-07
**Read first:** `.10x/decisions/product-manager/rag-search-redesign.md`; tracker #272.

### Next top priority (owner 2026-10-07): RAG search redesign
**A. Defects, in this order:**
1. SYS-93 #262: escape the answer.
2. SYS-92 #261: topic filter.
3. SYS-94 #263: answer states.
4. SYS-95 #264: names and dates.
5. SYS-96 #265: accessibility.
6. SYS-97 #266: conversation thread.

**B. The answer:**
- SYS-98 #267: shared Summarizer. Ask the owner for the provider first; an ADR is required.
- SYS-99 #268: prompt and citations.

**C. Copy, filters, look:**
- SYS-101 #270: copy table.
- SYS-100 #269: filters.
- SYS-102 #271: visual. The owner approves a mockup first.

**Process:**
- Issue-first and dev/QA roles as usual: dev labels `status: ready-for-qa`; QA closes.
- The new label `area: web` covers `newscrawler/web/`.

### Still for QA on 2026-10-07 (from the QA handoff below)
- SRC-58 at the 07:00 crawl.
- SRC-59 (INVESTORID) at 07:00.
- The 12:00 newsletter for OPS-43.

---

## Previous (superseded)

## From: QA -> To: SDE (fixes), QA of 2026-10-07 (scheduled runs)
**Date:** 2026-10-06 (night)
**Read first:** `.10x/reviews/2026-10-06-qa-report.md`; `.10x/decisions/qa/qa-pass-2026-10-06-night.md`.

### Verdicts
- **Closed:** SYS-90 #255, OPS-39 #232, DBT-01 #20, SYS-86 #246, SYS-80 #236, SYS-87 #247, OPS-44 #248, SYS-88 #249, DBT-56..59 (#251-#254).
- **Held:** SRC-58 #231. Today's crawls ran before the fix.

### For SDE, in order
1. **SRC-59 #260 (P2), INVESTORID.** `sitemap_news.xml` answers 404 since the 19:00 run. Confirm at 07:00 that it persists, then move to `sitemap.xml` / `sitemap_post.xml` (`lastmod`-only, the SYS-32 path).
2. **OPS-46 #259.** Isolate `TELEGRAM_OUTBOX` in `tests/integration/conftest.py`; until then, every integration run sends the owner 10 junk alerts at the next real send.
3. **SYS-91 #257.** Fix the `posted_at` of 88 CNBC docs in the FAISS metadata. This is a production FAISS write: owner approval, run lock, backup.
4. **DBT-60 #258.** The validator should also convert (or refuse) a str/float yyyymmdd.

### For QA, 2026-10-07
- **07:00 crawl, SRC-58:**
  - PIKIRANRAKYAT's note says `62 skipped, cannot load` and its phase is well under 147 s;
  - KONTAN / OKEZONE / BERITASATU report `gone`. Then close.
- **INVESTORID at 07:00:** still 404? (SRC-59).
- **05:30 health check:** no OPS-39 orphan line expected. The extraction row #2168 started 22:42 WIB; an orphan line would appear only if it were still `started` after 06:42.
- **12:00 newsletter:** the first scheduled edition with a working key. OPS-43 #243 needs 3 such runs, and the tracker its 7 editions.

### Risks
- **SRC-58:** a DNS server answering NXDOMAIN wrongly for a live regional host would skip it for that run. It is reported as `skipped`.

---

## Previous (superseded)

## From: SDE -> To: QA (verify), owner (SRC-47)
**Date:** 2026-10-06 (night)
**Read first:** `.10x/decisions/sde/p3-bug-burndown-2026-10-06.md`; EXPERIMENTS.md entries of 2026-10-06 (SRC-58, DBT-01/SYS-90).

### Ready for QA (evidence on each ticket)
- **SRC-58 #231:** watch PIKIRANRAKYAT's sitemap-phase time and the crawl_log notes (`did not load | gone | skipped`) at the next scheduled crawl.
- **OPS-39 #232:** the next 05:30 health check should send no crawl_log line (0 orphans after the cleanup).
- **DBT-01 #20.**
- **SYS-90 #255:** found while doing DBT-01.

### Owner
- **SRC-47 #157:** deferred 2026-09-25, to be re-read before OPS-19's first unattended run (it started 2026-09-26). Re-measured 2026-10-06 (see the ticket comment): keep it deferred, or schedule it?

### What to test
- Mutants `src58_*`, `ops39_*`, `sys90_*`, `dbt01_*` in `qa_mutation_runner.py` (21, all killed in a worktree).
- Integration: `test_crawl_log_orphans_live.py` and `test_sitemap_dto_dates_live.py`, which include the scripts' dry run, apply and restore.
- `scripts/experiments/probe_dead_branches.py` re-checks the dead-branch facts.

### Risks
- **SRC-58:** the DNS skip trusts NXDOMAIN only while the index host resolves. A DNS server that wrongly answers NXDOMAIN for a live regional host would skip it for that run. It is reported in the note ("skipped").
- **SYS-90:** the validator treats any int in 10000101-99991231 as a date. No other int should ever reach `timestamp`.

---

## Previous: From SDE -> To: QA (verify), owner (two decisions)
**Date:** 2026-10-05 (night)
**Read first:**
- `.10x/decisions/sde/newsletter-5min-edition.md`, section "QA's findings fixed".
- EXPERIMENTS.md, "2026-10-05 (night) — SDE fixes of QA's tracker #244 findings".

### Ready for QA (Done-when evidence on each ticket)
- SYS-86 #246, SYS-80 #236, SYS-87 #247, OPS-44 #248.
- DBT-56 #251, DBT-57 #252, DBT-58 #253, DBT-59 #254 (found here).
- SYS-88 #249: code, and the backfill applied 2026-10-06 05:59 (owner approved): 2,410 rows, the Done-when's query returns 0; undo with `--restore backups/sys88_headlines_20261006_055952.json`.

### Owner
1. **SumoPod prepaid balance ran out at ~23:00** (owner: not topped up). Top it up before 2026-10-06 12:00, or that newsletter has no summaries: headline lists, no edition, and "Edisi 5 menit tidak tersedia". The 21:00 extraction also stops at the first calls until it is topped up.
2. ~~Approve SYS-88's production write~~: approved and applied 2026-10-06 05:59.

### What to test
- Unit / integration suites; the mutants in `qa_mutation_runner.py` (`sys86_*`, `sys80_*`, `sys87_*`, `sys88_*`, `ops44_*`, `dbt5*`).
- Re-measure offline from the dumps:
  - `check_story_subjects.py --dir digests/preview/replay-v7 --dates 2026-10-03 2026-10-04`;
  - `probe_echo_guard.py --dir digests/preview/replay-v6 --dates ... --all-pairs`.
- v7's 09-24 is partial; 09-25 and 09-28 are invalid (budget).
- QA's own set (`scripts/experiments/qa_newsletter_244/`) passes 49/49. Two of QA's mutants in `qa_mutants_244.py` no longer match the code (`run_pdf_ok_always`, `run_message_skipped_on_fail`): `_deliver` changed for OPS-44. Equivalents are in `qa_mutation_runner.py` (`ops44_*`, `ops43_pdf_never_sent`).

### Risks
- **SYS-86 is exactly at its limit:** 1 wrong hide on 5 untuned days. The 7 scheduled editions are the real test.
- **SYS-80 demotion:** a related article the check cannot match (a spelling variant) loses its link and portal on the retry. This can lower a story's portal count, and so its rank in the edition.
- **Numbers held to `terkait`:** when the model wrongly marks a related article `tidak_terkait` and uses its number, the story can fall back. That happened to 2 stories on ~10 replayed days.

---

## Previous: From QA -> To: SDE (fixes), QA of 2026-10-06+ (scheduled runs), owner
**Date:** 2026-10-05 (night)
**Read first:**
- `.10x/reviews/2026-10-05-qa-report.md`;
- `.10x/decisions/qa/newsletter-5min-edition.md`;
- QA's test set and probes: `scripts/experiments/qa_newsletter_244/`.

### Verdicts
- **Closed:** SYS-81 #237, OPS-41 #238, SYS-84 #241, SYS-85 #245.
- **Sent back:** SYS-80 #236. The v5 re-render shows the "10 Saham" link and a FORU bullet under the Haji Isam headline (DB: the articles share no subject).
- **Held:** SYS-82 #239 (owner hand-check), SYS-83 #240 (owner phone read, scheduled run, SYS-86), OPS-42 #242 (owner phone), OPS-43 #243 (3 scheduled runs).

### For SDE, in order
1. **SYS-86 #246 (P2), echo guard.** Hiding distinct events breaks the "≤ 1 wrong hide" criterion. Re-measure on untuned days with `probe_echo_real.py`.
2. **SYS-80 #236.** Make the `terkait` outcome robust, or agree a scripted, measurable Done-when with the PM.
3. **SYS-87 #247, OPS-44 #248, SYS-88 #249 (P3).** Also the test gaps **DBT-56 #251, DBT-57 #252, DBT-58 #253**, each closed by killing its named mutant in `scripts/experiments/qa_newsletter_244/qa_mutants_244.py`. SYS-88's backfill needs the owner's approval for a production write.
- **SYS-89 #250** is an enhancement for the PM to scope.
- When fixed, these turn green: QA tests `TestSYS83EchoGuard` and `test_decimal_shift_is_a_different_number`.

### For QA, 2026-10-06 12:00 (first scheduled edition)
- **Files:** both files in `digests/`, `_edition` in the `newsletter_digests` row.
- **Hidden lines:** judge every `echoes_hidden` line (SYS-86).
- **Telegram order:** operator line, then the message, then `-ringkas.pdf`; no full digest. Quote `logs/scheduled_newsletter_*.log` on OPS-43.
- **Checks:** run `scripts/experiments/qa_newsletter_244/check_real.py` adapted to `digests/`. Compare with the previous day's edition for SYS-89.

### Risks
- **SYS-86:** a wrong hide silently removes a distinct story from the delivered edition. It stays in the archive.
- **Unreplayed outputs:** the editor's and the summarizer's judgements vary run to run. The scheduled editions are the first unreplayed output.

---

## Previous: From CTO (+ SDE build) -> To: QA — newsletter edition decisions
**Date:** 2026-10-05 (evening)
**Read first:** `.10x/decisions/cto/newsletter-5min-edition.md` (decisions, success criteria, review point); then the SDE handoff below.

- Owner-aligned: no non-finance quota; judul ask 10 / accept 12; the day's 6 largest stories always shown (top story or an untrimmable Sekilas line); a Sekilas line repeating a top story is hidden (`_edition.echoes_hidden`). Built in 5fe7859.
- QA success criteria (first 7 scheduled editions): <= 1,200 words; >= 95% summaries after the retry; >= 5 of the 6 largest stories shown each day; 0 events shown twice; review `echoes_hidden` (<= 1 wrong hide); newsletter cost <= $0.05/day. Review the decision after those 7 editions, or earlier if a criterion fails twice.

---

## Previous: From SDE -> To: QA (and the owner) — newsletter 5-minute edition
**Date:** 2026-10-05 (evening)
**Read first:** `.10x/decisions/sde/newsletter-5min-edition.md` (decisions, deviations, open items); EXPERIMENTS.md "2026-10-05 — SYS-82/SYS-83/OPS-42 replay"; tracker #244.

### Built (commits 654a81e, 5dacec7, a90067e, 81f7483)
`core/newsletter_copy.py` (SYS-81/84), `core/story_summary.py` (SYS-82/80), `core/newsletter_edition.py` (SYS-83), `core/newsletter_pdf.py` (OPS-41/42), `scripts/run_scheduled_newsletter.py` + `notify_telegram.send_html` (OPS-43), SOURCE_AUTHORITY key (SYS-85). Replay tool: `scripts/experiments/replay_newsletter_edition.py` (read-only DB, live LLM).

### Labelled `status: ready-for-qa` (Done-when evidence on each ticket)
SYS-80 #236, SYS-81 #237, OPS-41 #238, SYS-84 #241, OPS-42 #242 (Done-when changed by owner decision; owner phone read pending), OPS-43 #243 (needs three scheduled 12:00 runs), SYS-85 #245.

### Not labelled — targets missed, owner/PM decision on the ticket
- SYS-82 #239: first try 46-62% (target 90); after retry 96.7 / 100 / 92.7% (target 95). The model overshoots word limits by 1-3 words; most remaining fallbacks are a judul of 11-12 words. Options on the ticket.
- SYS-83 #240: coverage 4/6 on 09-28 (target 5); one event shown twice on 09-28 (Trump/Iran), one borderline on 10-03. Finance-first is prompt-only (5/8 non-finance on 10-04).

### What to test
- `tests/unit` (2,292 passed) and `tests/integration` (183 passed); the newsletter mutants (`sys8x_*`, `ops4x_*` in `scripts/experiments/qa_mutation_runner.py`).
- The first scheduled 12:00 run on this code (2026-10-06): both files in `digests/`, `_edition` in `newsletter_digests.categories`, Telegram = operator line + 60-second message + `-ringkas.pdf`; the full digest is NOT sent.
- `replay_newsletter_edition.py --check-only --date <d>` on the scheduled files: no English month, ISO date, source enum, telemetry; no PDF page starting on a link line.

### Risks
- ~130 LLM calls/day instead of ~103 (retries); ~$0.01/day.
- The phone PDF is 7 pages, not 6 (owner-accepted layout).

---

## Previous: From PM -> To: Architect / SDE (newsletter 5-minute edition)
**Date:** 2026-10-05
**Read first:** `.10x/decisions/product-manager/newsletter-5min-edition.md`; tracker #244.

### Requirements, in build order (each ticket's Done-when is the acceptance criterion)
1. SYS-81 #237 (bug P3): Indonesian, locale-independent dates. OPS-41 #238 (bug P3): PDF keeps a whole story per page.
2. SYS-82 #239 (P0): structured per-story summary (prompt in the ticket) + guards: JSON, word limits, number guard, retry then fallback. Fixes SYS-80 #236 (bug P2) via `terkait`.
3. SYS-84 #241 (P1): reader-facing copy table, outlet brand names, AI disclosure, degraded notice at the top.
4. SYS-83 #240 (P0): editor pass (prompt in the ticket), finance-first with >= 2 non-finance, 60-second block, Sekilas, <= 1,200 words, `digests/YYYY-MM-DD-ringkas.md`; full digest unchanged as archive.
5. OPS-42 #242 (P1): phone-first PDF of the edition. OPS-43 #243 (P1): Telegram message + edition PDF; the full digest is not sent.

### Constraints
- No schema change (edition stats under `_edition` in `newsletter_digests.categories`). Clustering (SYS-40/65/67) is out of scope.
- The replay on 2026-09-28 / 10-03 / 10-04 is part of SYS-82 and SYS-83's Done-when; log it in EXPERIMENTS.md. The owner hand-checks 20 stories and times one edition on the phone.
- Dev marks `status: ready-for-qa`; QA closes, and checks the tracker's success criteria on the first 3-7 scheduled editions.

---

## Previous: From QA (+ CTO/PM decisions, dev fixes) -> To: QA of the next days, and the owner
**Date:** 2026-10-04 (night)
**Report:** `.10x/reviews/2026-10-04-night-qa-report.md`; decisions `.10x/decisions/{cto,product-manager,qa}/night-2026-10-04-*.md`; ADR-004.

### Watch in the next 24 h (QA closes these when seen)
- **2026-10-05 05:30** health check; **07:00** crawl (first for SRC-57's 3rd run, SYS-64 day 2).
- **12:00 newsletter** (first scheduled): `newsletter_digests` row for 2026-10-04 replaces the stray partial row; Telegram line with `x/y summaries`; owner reads it (SYS-40, SYS-65). `scheduled_newsletter_*.log` for the first real run.
- **21:00 extraction** (first scheduled): Telegram line `n/m extracted ... pending a -> b`; `crawl_log` task `extract_knowledge`; non-finance topics now; cost per 1,000 ~$0.33; the 8 articles that failed on the old cap should extract (SYS-78). Close #125 and #136 on this evidence.
- Owner: confirm the two Telegram messages of the DB-liveness drill (21:16-21:18 WIB 10-04: "DOWN" then "RECOVERED"), then QA closes OPS-36 #209.

### Done since: SYS-73
The repair ran for every source on 2026-10-05 03:19-06:09 (see status.md); #223 is closed. QA: the nightly extraction re-extracts the 2,530 reset articles; if their entities look wrong, the backup rows are in `backups/sys73_<SOURCE>_*/rows.json`.

### Not done
SYS-74, SYS-41, SRC-34, SRC-47/42/40/39, SRC-58, OPS-39, DBT-01. Lower `KNOWLEDGE_DAILY_COST_LIMIT_USD` to 3 when the backlog is gone.

### Risks
- The extraction job loads the whole pipeline (~4 GB) at 21:00; it waits up to 90 min for a running crawl, else exits 2 (visible only in Task Scheduler).
- 4 workers have been tested at 4 with no 429; a per-minute 429 gets one wait-and-retry on DeepSeek, five failures in a row stop the run and say so.

---

## Handoff History
- 2026-10-06 (night) SDE -> QA/owner: P3 burn-down (SRC-58, OPS-39, DBT-01, SYS-90 ready-for-qa; SRC-47 re-measured for the owner) (this file, top).
- 2026-10-05 (night) SDE -> QA/owner: QA's #244 findings fixed; 8 ready-for-qa, SYS-88 backfill and the SumoPod top-up await the owner (this file, top).
- 2026-10-05 (night) QA -> SDE/QA/owner: tracker #244 verified; 4 closed, SYS-80 sent back, 4 held, 8 filed (this file, top).
- 2026-10-05 (evening) CTO -> QA: edition decisions built and replayed (this file, second).
- 2026-10-05 SDE -> QA/owner: newsletter 5-minute edition built and replayed (this file, top).
- 2026-10-05 PM -> Architect/SDE: newsletter 5-minute edition, tracker #244 (this file, top).
- 2026-10-04 night QA/CTO/PM -> QA: P1/P2 pass (this file).
- 2026-10-04 PM -> SDE: SYS-39 (extract all news on DeepSeek, peak guard). Picked up and built (see above).

- 2026-10-04 SDE -> QA (still pending QA): SYS-71 #219, SYS-72 #220, DBT-51 #221, DBT-52 #222 ready-for-qa, #216/#215/#204 re-labelled; #204 needs the 19:00 crawl; stray partial-day 2026-10-04 digest row awaits the owner. Full text: `decisions/sde/p1-p2-newsletter-fixes.md`, section "QA feedback fixed".
- 2026-10-04 QA -> SDE: fix SYS-71 first, then SYS-72, DBT-51, DBT-52; owner approved task=newsletter, SYS-67 as scoped, SYS-63 repair after SYS-72.

- 2026-10-04 planning -> SDE: P1/P2 fixes + newsletter (spec + ADR-001, ADR-002).
- 2026-10-04 brainstorming -> QA: verification of 9 ready-for-qa tickets (baseline done, see decisions/qa). QA pass is paused while dev work runs; scheduled-run evidence still pending.
- 2026-10-04 init-project -> first active role: state initialized.
