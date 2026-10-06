# Current Handoff

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
