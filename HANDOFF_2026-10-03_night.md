# QA handoff — `HANDOFF_2026-10-03.md` Phase 1 + Phase 3, worked (2026-10-03, night)

Paste this as the opening prompt of a **QA** session, or point the session at this file. It answers the dev list in `HANDOFF_2026-10-03.md`. The owner chose **Phase 1 + Phase 3** for this session.

- **7 tickets are `status: ready-for-qa`:**
  - SYS-66 #213, SYS-70 #218, SRC-57 #206 (Phase 1);
  - OPS-35 #207, SYS-64 #208, OPS-37 #210, OPS-36 #209 (Phase 3).
- **Not started, by design:** SRC-56 #205 (TEMPO). It waits for the owner's browser test; its dated checks live in SYS-70.
- **One ticket's diagnosis was wrong, and the fix differs from its text. Read this first.** SYS-66 said PIKIRANRAKYAT's 727/896 burst was a host refusing us. It was **dead DNS**: retired regional brand subdomains that no longer resolve. Counting every `ConnectionError` in SRC-55's breaker, as the ticket proposed, would have starved PIKIRANRAKYAT forever. Dead hosts are named apart (`NameResolutionError after N retries`) and never count.
- **Owner decisions this session:**
  - Throughput kept (20 threads), with per-host pacing only where measured (KUMPARAN 1 req/s).
  - Bot UA `NewsAggregatorBot/1.0`, with the browser UA kept for BERITASATU, INVESTORID and TRIBUN (they 403 the bot).
  - No contact in the UA yet.
  - OPS-18 floors 0.80/0.70 accepted (comment on #123).
  - TEMPO not retired.
- **One config change outside git:** `.env` `REQUEST_MAX_RETRIES` 5 → 3, since with backoff 5 costs ~23 s per dead-host URL. The old `.env` is not kept in the repo.
- **No production DB writes.** Live checks were read-only: `check_crawlers.py` to a scratch report dir, `probe_bot_ua.py`, `db_liveness.py --check`.
- **Everything here first runs in the scheduled crawl at 2026-10-04 07:00. Read the risk list.**

Read in this order:
1. `CLAUDE.md`: the "Sitemap crawl" step gains OPS-35's failure and a "Fetching (SYS-66/SYS-70)" paragraph; the ID map runs through SYS-70 = #218.
2. `EXPERIMENTS.md`: one new trap line (dead DNS vs refusal), then the entry "SYS-66/SYS-70: bot User-Agent across the fleet, fetch share of run time, and PIKIRANRAKYAT's 'refusal burst' was dead DNS".
3. `OPERATIONS.md`: 11 new env rows (`REQUEST_*`, `CRAWLER_*`, `BROWSER_UA_HOSTS`, `HOST_*`, `FAISS_RENAME_*`, `AUDIT_MIN_JUDGED_SHARE`, `FILTER_AUDIT_TIMEOUT_S`, `DB_LIVENESS_*`); `SCHEDULE_SOURCE_TIMEOUTS` gains `KUMPARAN=1800`; the drift-audit section gains "It never fails silently"; a new section "DB liveness (OPS-36)"; the schedule table has the unregistered liveness row.
4. The dev comment on each ticket: Done-when evidence and what is still open.

---

## Suites and tree

| | at `addbdb0` | now |
|---|---|---|
| `tests/unit` | 1,580 passed, 5 skipped | **1,642 passed, 5 skipped** |
| `tests/integration` | 156 passed | **156 passed** |
| `qa_mutation_runner.py` | 113 registered | **140 registered**; the 27 new: **27 KILLED / 0 SURVIVED** (baseline under the runner env: 1,642 passed, so the kills are real) |

Commits on `dev`, **not pushed**:
- `246ff76` SYS-64
- `e9840d2` SYS-66 + SYS-70 (+ SRC-57)
- `99c5081` OPS-35
- `8c38fe5` OPS-37 (+ OPS-18 alert-path tests)
- `8d22987` OPS-36
- `c4628aa` docs + 27 mutants
- this file

---

## Ready for QA

| Ticket | What changed | Live / scheduled evidence still needed |
|---|---|---|
| SYS-66 #213 | Retries 3 with backoff 1/2/4 s ± jitter. DNS failure named `NameResolutionError after N retries`. `ConnectionError`/`ReadTimeout after N retries` count toward SRC-55's streak; DNS never does. | 10-05/06: PIKIRANRAKYAT's 989 dead-host rows re-enter. Expect a block of strikes, then retirement at 3 (correct). No source stopped by `ConnectionError after 3 retries` on a host that resolves. |
| SYS-70 #218 | `HostGate` per host/suffix (interval, concurrency, Retry-After defer). Bot UA except `BROWSER_UA_HOSTS`. Retry-After ≤ 60 s waited once. | Live fleet `check_crawlers.py`: OK = 27, FALLBACK = 0. **First scheduled run within budget: 10-04 07:00.** The check-later list (TEMPO re-test 10-06, owner browser test) is on the ticket. |
| SRC-57 #206 | KUMPARAN paced at 1 req/s via SYS-70; timeout 1,800 s. | 3 scheduled runs: "not fetched" falling or 0; no `throttled` note before 400 fetches; struck-403 query 0. |
| OPS-35 #207 | Dead index → `SitemapIndexUnavailable` → `failed` with the reason; all branches failing too; partial → note on a `completed` row. | TEMPO is **paused** since 23:18 (owner, SRC-56), so it will not show in the scheduled run. Check live with a one-off: `venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from newscrawler.application.api.lambda_function import lambda_handler; lambda_handler.process_event({'task': 'sitemap', 'website': 'TEMPO'}, None)"`. Expect a `crawl_log` TEMPO/sitemap row `failed` with `sitemap index did not load: HTTP 403` (writes one log row, nothing else). |
| SYS-64 #208 | FAISS commit rename and roll-forward moves retry `PermissionError` (0.2 → 3.2 s). | 7 days without a `WinError 5` row. |
| OPS-37 #210 | Shortfall = failed audit; `BaseException` closes the row; health check relays a failed audit as one alert; **new: the audit subprocess had no timeout, now 1,800 s**. OPS-18 send-back item 2 (alert-path tests) is done in the same commit. | 10-05 05:30, the first scheduled audit. |
| OPS-36 #209 | `scripts/db_liveness.py` with a client-side deadline; DOWN after 2 failures, RECOVERED once, no repeats. | **Owner:** register the job (command in OPERATIONS.md) and approve a drill that briefly stops production Postgres. |

## Not worked (by scope)

- OPS-18 #123 send-back item 1, the unreachable per-cell alert: a design change, not done. Item 2 (alert-path tests) is done.
- Phases 2, 4, 5, 6 of `HANDOFF_2026-10-03.md`: OPS-20 P1, SYS-63, the newsletter, SRC-34, hygiene.

## Risk list (all of this first runs at 2026-10-04 07:00)

1. **The bot UA reaches every source except the three exceptions.** Index, branch and article fetches were OK for all 27 in `check_crawlers.py` (2 samples each). A source could still treat a *volume* of bot-UA requests differently than a sample. Watch for new 403 walls in the run (the SRC-55 `throttled` notes) on sources other than KUMPARAN.
2. **KUMPARAN now runs ~1,000–1,300 s** (paced, whole queue) against an 1,800 s timeout. If it is killed, the pacing interval or the queue is wrong. Its FAISS vectors re-embed next run (the SYS-52 path).
3. **Retries now sleep.** A source with many connection failures runs longer: 3 retries ≈ 7 s per failing URL on 20 threads. PIKIRANRAKYAT's dead-host rows cost ~350 s once, then retire.
4. **TEMPO is paused** (owner, 2026-10-03 23:18; `DEFAULT_EXCLUDED`, citing SRC-56). The run log says `SKIPPED TEMPO: SRC-56 (#205) …`. The 05:30 health check still samples it and alerts RECOVERED if the block lifts. Owner browser test: real browsers get in, automated clients don't, so it's a fingerprint block, not an IP ban.
5. **SRC-55's streak now counts refusals and timeouts.** A source with a burst of 10 timeouts in a row stops for that run without stamping its rows. That is intended; watch for a source that stops at the same spot every run (unstamped rows at its queue head).

## What to mutation-test beyond the 27

- `RequestsPageLoader.get_url_with_reason`'s loop bounds (attempt counting with a Retry-After in the middle).
- `HostGate.slot` when the semaphore is acquired but the interval sleep raises.
- `SitemapListing` passed through `batch_crawling_sitemap` by a subclass that returns a plain list.

## Decisions waiting on the owner

- OPS-36: register the liveness job, and approve the drill.
- SRC-56: the browser test (this network vs mobile data).
- Whether to put a contact in the bot UA (`CRAWLER_CONTACT`).

## How to report back

As usual: close or send back each of the 7 with what you checked, file new tickets for anything found, and write `HANDOFF_<date>.md` for dev.
