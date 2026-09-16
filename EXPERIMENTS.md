# Experiment Log

Append-only record of things we tried — probes, hypothesis tests, approaches, benchmarks — whether they worked or not. **Write the entry in the same session the result is known.** Failed and inconclusive experiments matter most: they are what stops future-us from repeating them.

Entry format:

```
### YYYY-MM-DD — short title
- **Question / hypothesis:** what we wanted to know
- **Method:** exact command, or path under scripts/experiments/, or inline snippet
- **Result:** numbers, statuses, exact error text
- **Conclusion / do not repeat:** what we now believe and what not to try again
- **Links:** issue #, commit, related files
```

Reusable diagnostics live in `scripts/experiments/`. Throwaway repro code is inlined in the entry.

---

## Traps & settled questions

One line each; read this before starting on a scraper or pipeline problem.

- **Changing the User-Agent does not fix any current sitemap failure.** All 32 sitemap URLs return the same status with the 2017 default UA and a modern Chrome UA. 403s (BISNIS, IDNTIMES) are server-side bot protection, 404s are dead URLs. → [2026-09-15 UA probe](#2026-09-15--user-agent-is-not-why-sitemaps-fail)
- **A "BROKEN" scraper is usually not a layout change.** Of 14 unhealthy outlets on 2026-09-15, only 2 were article-layout changes; 5 were dead URLs, 2 were 403s, 1 TLS, 3 sitemap-format changes, 1 crawler crash. Check the sitemap URL and index format first. → [2026-09-15 health check](#2026-09-15--full-health-check-of-all-32-crawlers)
- **"OK" in `check_crawlers.py` can hide a dead selector.** CNBC, CNN, KONTAN, PIKIRANRAKYAT pass only because trafilatura rescued them. Until #10 lands, grep the run log for `Standard extraction failed`. → same entry
- **A site extractor returning `[]` is NOT rescued by the fallback chain; only `None`/`""` is.** Don't "fix" a scraper by making it return an empty list. → [2026-09-15 mocked repros](#2026-09-15--mocked-repros-of-suspected-silent-failure-bugs) · #2
- **`get_session()` swallows exceptions — a DB write that "succeeded" may not have.** Any test or script that reads back from Postgres must check the row exists; don't trust a non-raising call. → same entry · #4
- **A missed crawl run cannot be backfilled from the sitemap** because of the pre-dedup date gate; `backfill_missing_articles.py` only re-crawls sitemaps already in the DB. → same entry · #8
- **The `worktree-phase1-migration` branch is superseded; do not resurrect it.** Its chunker tests target a removed API (`_MIN_TOKENS`). Its only unique file was `scripts/migrate_posted_at.sql`, already carried over. → [2026-09-16 worktree check](#2026-09-16--is-the-orphaned-worktree-branch-still-needed)
- **Broken crawlers on 2026-06-02 were verified non-transient** (fail single-threaded with a 90 s timeout), so re-running "just in case" is wasted time — fix the root cause. → [2026-06-02 entry](#2026-06-02--are-the-17-broken-crawlers-transient)
- **Ollama per-article embedding was replaced on purpose** (sequential HTTP round-trips, poor vectors for long articles). Don't reintroduce it; in-process `sentence-transformers` batching is the design. → `PRD.md` §6.5

---

## Log

### 2026-06-02 — Are the 17 BROKEN crawlers transient?
*(backfilled from session notes; no script retained)*
- **Question / hypothesis:** `check_crawlers.py` reported 17/32 BROKEN. Maybe it's thread contention or short timeouts, not real breakage.
- **Method:** re-ran the failing outlets single-threaded (`--workers 1`) with `--timeout 90`.
- **Result:** every one of the 17 still failed.
- **Conclusion / do not repeat:** the failures are real (URL/format rot). Don't re-run with bigger timeouts as a diagnostic; go straight to the sitemap URL and `_get_branches`.
- **Links:** memory notes; superseded by the 2026-09-15 health check below.

### 2026-06-02 — Why do sitemaps have thousands of rows but almost no articles?
*(backfilled)*
- **Question / hypothesis:** WARTAEKONOMI had 6,992 sitemap rows and 8 articles. Suspected the semantic filter was too strict.
- **Method:** traced a single sitemap through `_crawl_newsdetails_inner` → `save_chunk_data` → `save_newsdetails_data` with logging; queried `articles` for `DatatypeMismatch` errors.
- **Result:** two bugs, neither the filter. (A) FAISS dedup returned already-embedded chunks with `embedding_id=None`, `save_chunk_data` filtered on `embedding_id`, returned nothing, article never saved. (B) No "attempted" marker on sitemaps, so filtered/failed ones were re-selected forever. Underneath, article INSERTs had been crashing for days on `is_embedded` int/bool and `article_id NOT NULL` mismatches.
- **Conclusion / do not repeat:** when articles are missing, check `crawl_log`/DB errors before tuning the filter threshold. Schema drift between `table.py` and the SQL migrations is a recurring cause.
- **Links:** `scripts/migrate_sitemap_crawl_attempt.sql`, `scripts/backfill_missing_articles.py`, tests `test_save_chunk_data.py`, `test_mark_attempted_wiring.py`.

### 2026-09-15 — Full health check of all 32 crawlers
- **Question / hypothesis:** which scrapers are actually broken today, and why?
- **Method:** `venv\Scripts\python.exe scripts/check_crawlers.py --sample-size 2` (all outlets, real code paths, live network).
- **Result:** 18 OK · 2 PARTIAL (KUMPARAN, OKEZONE) · 11 BROKEN (ANTARANEWS, BATAMPOS, BISNIS, IDNTIMES, INEWS, KAPANLAGI, LIPUTAN6, MERDEKA, SUARA, TEMPO, TIRTO) · 1 ERROR (EMITENNEWS, `TypeError: argument of type 'NoneType' is not iterable`). Full table in `AUDIT_2026-09-15.md` Appendix A. Run log showed `Standard extraction failed … Trafilatura fallback` on every sample for CNBC, CNN, KONTAN, PIKIRANRAKYAT.
- **Conclusion / do not repeat:** the set of broken outlets changed since June (BISNIS newly 403; ERAID, INVESTORID, KONTAN, MEDIAINDONESIA, TRIBUN recovered on their own — likely sitemap CDN flakiness at the time). "OK" ≠ "site extractor works". The check must be scheduled and must distinguish fallback rescues (#9, #10).
- **Links:** `AUDIT_2026-09-15.md`, tracker #25.

### 2026-09-15 — User-Agent is not why sitemaps fail
- **Question / hypothesis:** the page loader still sends a 2017 `Chrome/56` UA; maybe bot protection is blocking the sitemap fetches.
- **Method:** `scripts/experiments/probe_sitemap_ua.py` — every `URL` enum value fetched with the default headers and with a modern Chrome/128 UA; status, size, content-type compared.
- **Result:** identical status codes for all 32. Non-200s: ANTARANEWS 404 (URL is an *English sports RSS feed*), BATAMPOS 404, KAPANLAGI 404, TIRTO 404, REQNEWS 404 (unused), BISNIS 403 (5 KB HTML challenge page), IDNTIMES 403 (empty body), INEWS `SSLError: CERTIFICATE_VERIFY_FAILED`. BERITASATU returns `application/rss+xml` but its crawler handles it.
- **Conclusion / do not repeat:** don't spend time on UA rotation for the sitemap layer. For BISNIS/IDNTIMES the options are another endpoint (RSS, `/robots.txt` Sitemap lines), richer headers (`Referer`, `Accept-Language: id-ID`, `Sec-Fetch-*`) — untested — or the headless loader. Re-run the probe after any header change to see if it moved the needle.
- **Links:** #13, #14, #15.

### 2026-09-15 — Mocked repros of suspected silent-failure bugs
- **Question / hypothesis:** four code-reading suspicions in the crawl path — do they actually misbehave?
- **Method:** scratch script with a `Crawler` subclass whose `page_loader.get_soup` is stubbed and `newspaper.Article` patched; `requests.get` patched to raise; `NewsDataSource` with a `MagicMock` sitemap datasource. No network, no DB. Key snippets:
  ```python
  # SYS-01: extractor returns [] vs None
  class C(Crawler):
      def _get_whole_text(self, soup): return self._ret     # None  or  []
      def _get_reporter_from_text(self, soup): return []
  # SYS-05: which exceptions get retried
  with patch("...requests_page_loader.requests.get", side_effect=ConnectionError): pl.get_url("http://x")
  # SYS-07: date gate, last max posted_at = 2026-09-01
  ds.save_sitemap([posted 09-15, posted 08-30, posted 09-01 00:00, posted 09-01 09:00])
  ```
- **Result:**
  - `None` → trafilatura fallback used ✔; `[]` → `extracted_text=[]`, no fallback ✘.
  - `ConnectionError` → 1 attempt (never retried); `ReadTimeout` → 6 attempts.
  - Date gate kept 09-15 and 09-01 09:00; **dropped** 08-30 and 09-01 00:00 although never seen.
  - Bonus: `SitemapDTO(timestamp=None)` raises under pydantic 2.11 (repo pins 1.7.3) — undated sitemap entries are silently dropped per-entry in `_get_sitemap`.
- **Conclusion / do not repeat:** all confirmed; filed as #2, #6, #8, #20. These snippets should become the regression tests when each is fixed.
- **Links:** `AUDIT_2026-09-15.md` SYS-01/05/07, DBT-01.

### 2026-09-15 — Read production `crawl_log` to see how long sources have been dead
- **Question / hypothesis:** can the DB tell us when each source stopped producing articles?
- **Method:** read-only SQL over `crawl_log` and `sitemaps LEFT JOIN articles` via `SQLAlchemyClient`.
- **Result:** Postgres was not running (`connection refused` on 5431). The script printed its first header and continued silently — `get_session()` swallowed the `OperationalError`.
- **Conclusion / do not repeat:** inconclusive on the original question — **still to do once the DB is up** (first step of #5). Incidentally proved #4 live: a DB outage looks like success.
- **Links:** #4, #5.

### 2026-09-16 — Is the orphaned worktree branch still needed?
- **Question / hypothesis:** `worktree-phase1-migration` (1 commit, 5 uncommitted edits, 3 untracked files) might contain work not in `dev`.
- **Method:** `git diff --name-only dev worktree-phase1-migration` + per-file diff of the worktree's uncommitted edits against main; copied its `tests/unit/test_chunker.py` into main and ran pytest.
- **Result:** every committed file already present in main in a newer form. Uncommitted edits were older versions of the sitemap datasource / `table.py`. `test_chunker.py` failed at collection: `ImportError: cannot import name '_MIN_TOKENS' from 'newscrawler.core.chunker'` (API since rewritten). Only unique asset: `scripts/migrate_posted_at.sql`.
- **Conclusion / do not repeat:** superseded; worktree removed, branch deleted (recoverable via `git branch worktree-phase1-migration 0050e91`), migration carried over. Don't re-examine it.
- **Links:** commit `9b08107`.
