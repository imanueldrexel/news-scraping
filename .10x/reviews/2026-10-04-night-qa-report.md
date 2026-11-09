# QA report 2026-10-04 (night): P1/P2 verification against the tickets' own wording

**Scope:** every open P1/P2 and everything labelled `status: ready-for-qa`. **Method:** each ticket's Done-when read first; the check is then chosen to match it: real data (production read-only, the test database for anything that writes), the real entry points, real model calls for the digest and extraction work, and an independent mutation run in a clean `git archive` copy of HEAD. The dev's unit tests were not taken as evidence.

## Verdicts

| Ticket | Verdict | Evidence that is not a unit test |
|---|---|---|
| SYS-63 #204 (P2) | held for 3 stale mutants (retargeted, re-run in batch 2) | 19:00 crawl rows (1,741 articles): Baca/Lihat juga + chrome <= 2% for every source; the one TVONENEWS hit is prose ("dapat dilihat juga") |
| OPS-35 #207 (P2) | **closed** | live: TEMPO raises `SitemapIndexUnavailable` (HTTP 403); `process_event` on the test DB writes a `failed` crawl_log row; production notes name partial index failures; 4/4 mutants |
| OPS-37 #210 (P2) | **closed** | live on the test DB: missing key -> `failed` row with the SystemExit text, not `started`; 4/4 mutants |
| SYS-71 #219 (P2) | **closed** | three real digests with the live summarizer finished 96/96, 95/95, 92/92; 5/5 mutants |
| SYS-72 #220 (P3) | **closed** | whole-corpus dry run: 0 bodies emptied, chrome 24.7% -> 0; 4/4 mutants |
| SYS-67 #215 (P2) | **sent back, fixed, closed** | real digest 2026-09-28: Cibinong 4 of 8 slots (ticket: 5) because the grouping call split one scandal into 3 stories and was unstable; new prompt probed 5/5 identical on a committed real fixture, then 3 of 8 in the full digest (the third is a contaminated cluster = SYS-74); no over-merge on two other sections; 18/18 mutants |
| SYS-68 #216 (P2) | held for 1 stale mutant (retargeted) | real digests: footer `Ringkasan AI: 96/96 (deepseek-v4-flash)`, 0 clusters without a bullet summary |
| SYS-66 #213 (P2) | held | 5/5 mutants; strikes did not burst (PIKIRANRAKYAT 7 transient strikes after two runs); the "989 parked rows fetched on their next visit" half needs the cooldown to expire (~2026-10-09) |
| SRC-57 #206 (P2) | held | KUMPARAN: no throttle note in either run, 0 HTTP 403 strikes, no never-attempted rows; needs the third run |
| SYS-64 #208 (P2) | held | 0 `WinError 5` rows since the fix, 0 failed crawl_log rows on 2026-10-04; needs 7 days |
| OPS-36 #209 (P2) | held for the owner | job registered; real drill (`docker stop`, 2 min): second failed probe -> DOWN, third probe repeats nothing, recovery probe -> UP, row counts identical; the two Telegram messages must be confirmed by the owner |
| SYS-75 #225 (P2) | see addendum | 116 real stored lines with prose before a widget: all 116 kept by the cleaner (the old cleaner deleted them) |

## New tickets from this pass (QA files them)
- **DBT-53 #226 (P2):** a mutation run executed `run_scheduled_newsletter.py` against production (the unit suite had no guard against a real database); fixed: `psycopg2.connect` refuses in unit tests, Telegram blank, guard tests patch `_run`; proof: the same mutant is killed without touching the digest row or file.
- **DBT-54 #227 (P3):** flaky thread-ordering test; fixed (12/12 stable).
- **SYS-76 #228, SYS-77 #229 (P2), closed:** the first real extraction stored the publishing outlet (30% of articles) and 189 distinct free-text event types; prompt fixed before the backlog run, measured before/after on 200 articles, then on the real run.
- **SYS-78 #230 (P2):** replies cut at the 1,200-token cap fail to parse on every retry (1 in ~100); cap raised, cut replies logged.
- **SRC-58 #231 (P3):** PIKIRANRAKYAT retries 62 unresolvable hosts every run (147 s), KONTAN requests a malformed branch URL.
- Retargeted 10 stale mutants (they matched 0 or 2 places after SYS-72/75/39 changed the code) and removed 2 for behaviour that no longer exists: all 270 registered mutants now match exactly once (`scripts/experiments/qa_mutation_runner.py` plus the static check used here).

## Not verifiable yet (scheduled-run evidence)
SRC-57 (3 runs), SYS-64 (7 days), SYS-66 (cooldown), OPS-38 (3 daily digests, first run 2026-10-05 12:00), OPS-20 #136 (see addendum).

## Residual risks recorded
- The grouping call is nondeterministic on borderline pairs (two political stories flip between runs); it only matters when a group exceeds the 2-slot cap.
- Locations mix Indonesian and English names (Amerika Serikat / United States); an alias-map question.
- Health check samples one branch per source: WARTAEKONOMI flagged STALE because its `agribisnis` branch is quiet, while the source saved 229-267 sitemaps/day on weekdays.
- Five `crawl_log` rows from May-September are still `started` (pre-OPS-11 orphans): OPS-39 (#232).
