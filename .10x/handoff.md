# Current Handoff

## From: CTO (+ SDE build) -> To: QA — newsletter edition decisions
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
- 2026-10-05 SDE -> QA/owner: newsletter 5-minute edition built and replayed (this file, top).
- 2026-10-05 PM -> Architect/SDE: newsletter 5-minute edition, tracker #244 (this file, top).
- 2026-10-04 night QA/CTO/PM -> QA: P1/P2 pass (this file).
- 2026-10-04 PM -> SDE: SYS-39 (extract all news on DeepSeek, peak guard). Picked up and built (see above).

- 2026-10-04 SDE -> QA (still pending QA): SYS-71 #219, SYS-72 #220, DBT-51 #221, DBT-52 #222 ready-for-qa, #216/#215/#204 re-labelled; #204 needs the 19:00 crawl; stray partial-day 2026-10-04 digest row awaits the owner. Full text: `decisions/sde/p1-p2-newsletter-fixes.md`, section "QA feedback fixed".
- 2026-10-04 QA -> SDE: fix SYS-71 first, then SYS-72, DBT-51, DBT-52; owner approved task=newsletter, SYS-67 as scoped, SYS-63 repair after SYS-72.

- 2026-10-04 planning -> SDE: P1/P2 fixes + newsletter (spec + ADR-001, ADR-002).
- 2026-10-04 brainstorming -> QA: verification of 9 ready-for-qa tickets (baseline done, see decisions/qa). QA pass is paused while dev work runs; scheduled-run evidence still pending.
- 2026-10-04 init-project -> first active role: state initialized.
