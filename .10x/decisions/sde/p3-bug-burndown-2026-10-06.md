# P3 bug burn-down (SDE, 2026-10-06)

Picked after the newsletter round went to QA, by the no-bug-carryover rule: open bugs before new work. Owner: "do that" (SRC-58 → OPS-39 → DBT-01 → SRC-47).

| Ticket | Built | Decision made here | Status |
|---|---|---|---|
| SRC-58 #231 | `requests_page_loader.host_resolves`; `Crawler.drop_unreachable_branches` (NXDOMAIN host or hostless `<loc>`: skipped unfetched; trusted only while the index host resolves); `is_gone_reason` (404/410/soft-404/bad redirect = gone); `SitemapListing.branches_gone/skipped`; note `did not load \| gone \| skipped`; `tests/unit/conftest.py` blocks DNS | **Owner (AskUserQuestion):** request the 404/bad-redirect branches and report them as gone; no per-crawler skip list. KONTAN `pressrelease` is a malformed *redirect*, not a malformed `<loc>` | ready-for-qa; PIKIRANRAKYAT 147 s → 50 s live |
| OPS-39 #232 | `newscrawler/tools/crawl_log_orphans.py` (per-task limit: extract_knowledge 8 h, others 4 h); 05:30 health-check line; `scripts/close_abandoned_crawl_log.py` (dry run / apply with backup / restore) | Per-task limit instead of a flat 4 h (the extraction may run 8 h). Owner approved the write: 5 rows closed | ready-for-qa |
| DBT-01 #20 | `requirements.txt` = venv `pip freeze` (resolves); `SitemapDTO.timestamp: Optional[datetime]` | Undated entries were already settled by SYS-32 | ready-for-qa |
| SYS-90 #255 (found) | `site_map_dto.posted_at_datetime` + before-validator; `_to_sitemap_dto`/`load_all_sitemaps` use it; `scripts/repair_article_posted_at.py` | Fixed at the DTO boundary so no caller can repeat it. Owner approved the repair: 193 rows | ready-for-qa |
| SRC-47 #157 | nothing | **Not started: owner deferred it 2026-09-25** ("<= 5%... P3, later"), with the condition "re-read before OPS-19's first unattended run". That run started 09-26 unread, so it was re-measured read-only (verify_branch_scope_live.py) for the owner to re-decide | awaits owner |

Production writes this round (all owner-approved, all with a JSON backup and `--restore`): `backups/ops39_crawl_log_20261006_212631.json` (5 rows), `backups/sys90_posted_at_20261006_220559.json` (193 rows).

Mutants added to `qa_mutation_runner.py`: `src58_*` (10), `ops39_*` (7), `sys90_*` + `dbt01_*` (4); all killed.

## Tech debt / residuals
- SRC-58: the "gone" branches are still requested once per run (~1 s each), by owner choice. A branch that 404s transiently for one run is labelled gone that run.
- SYS-87 residual still open: a digit inside a word of an article body (`Liputan6.com`) counts as a number for the newsletter's guard.
- `scripts/experiments/run_mixed_bucket_verification.py` still builds DTOs from stored rows; it is safe now because of the DTO validator.
