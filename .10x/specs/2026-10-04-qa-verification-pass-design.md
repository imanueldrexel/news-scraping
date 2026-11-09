# QA verification pass — 2026-10-04 (design)

**Feature slug:** `qa-pass-2026-10-04`
**Role:** QA (per CLAUDE.md dev/QA workflow). Dev does not close tickets; QA does.
**Approved by owner:** 2026-10-04 ("Approve as written").

## Goal
Independently verify every `status: ready-for-qa` ticket, then close it, send it back, or leave it open pending scheduled-run evidence. File a new ticket for every defect found.

## Scope: 9 tickets
SYS-66 #213, SYS-70 #218, SRC-57 #206, OPS-35 #207, SYS-64 #208, OPS-37 #210, OPS-36 #209, SYS-40 #126, SYS-20 #41.

Out of scope: dev work on open bugs (OPS-20, SYS-63, SYS-67/68/65/69, OPS-38, P3s), SRC-56 (owner browser test pending), OPS-18 per-cell alert design.

## Method
1. **Baseline:** `tests/unit` (expect 1,642 passed / 5 skipped), `tests/integration` (expect 156 passed), mutation runner on the 27 new mutants (`PYTHONDONTWRITEBYTECODE=1`), plus 3 extra mutation targets: `RequestsPageLoader.get_url_with_reason` loop bounds with a Retry-After mid-loop; `HostGate.slot` when the interval sleep raises; `SitemapListing` returned as a plain list by a subclass.
2. **Per-ticket independent checks (no prod DB writes):**
   - SYS-66 / SYS-64: code read + mutate retry count, backoff, DNS-vs-refusal split, `PermissionError` retry window.
   - OPS-35: one-off `task=sitemap` for TEMPO (writes one `crawl_log` row; ask owner first); expect `failed` with `sitemap index did not load: HTTP 403`.
   - OPS-37: shortfall / missing key / timeout paths against stubs.
   - OPS-36: `scripts/db_liveness.py --check`.
   - SYS-20: recount script in dry-run; check the DRIFT_SQL actually exercised by tests (see DBT-50).
   - SYS-40: compare digest structure with the sample digest; check topic ordering and per-topic cluster cap.
   - SYS-70 / SRC-57: `check_crawlers.py` to a scratch report dir; confirm bot UA / `BROWSER_UA_HOSTS` behaviour.
3. **Scheduled-run evidence** from `crawl_log` and logs for the 2026-10-04 07:00 run: `SKIPPED TEMPO`, KUMPARAN vs 1,800 s budget, new 403 walls on other sources, any `WinError 5`, bot-UA throttles.

## Verdict rules
- **Close** only when the Done-when has no scheduled-run part left; remove the label and comment what was checked.
- **Leave `ready-for-qa`** while scheduled evidence is outstanding: SYS-66 (10-05/06), SRC-57 (3 runs), SYS-64 (7 days), OPS-37 (10-05 05:30), SYS-70, OPS-36 (owner registers job and approves drill).
- **Send back** on failure: remove label, comment what fails.
- **New ticket** per distinct defect, next free ID per prefix, never a comment on an umbrella ticket.

## Safety
No production DB writes without asking the owner. Check that the 07:00 crawl is not mid-run (`.scheduled_crawl.lock`) before any live probe. Work in the main repo root only.

## Output
`HANDOFF_2026-10-04.md` for dev; `.10x/` state files updated.
