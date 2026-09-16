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
- **"OK" in `check_crawlers.py` can hide a dead selector.** CNBC, CNN, KONTAN, PIKIRANRAKYAT pass only because trafilatura rescued them. Until OPS-02 (#10) lands, grep the run log for `Standard extraction failed`. → same entry
- ~~A site extractor returning `[]` is NOT rescued by the fallback chain; only `None`/`""` is.~~ **Fixed 2026-09-16 (#2):** any result that is empty or under `MIN_ARTICLE_CHARS` (default 200) now falls through site → trafilatura → newspaper, and a failed fallback never replaces a shorter real result. → [2026-09-16 verification](#2026-09-16--does-the-2-fallback-fix-rescue-kumparan-live)
- ~~`get_session()` swallows exceptions — a DB write that "succeeded" may not have.~~ **Fixed 2026-09-16 (SYS-03):** it now rolls back and re-raises. Call sites that must tolerate a DB error (`crawl_log` writes, web UI, `check_crawlers --log-db`) have their own try/except. **But a DB outage still exits 0** — the constructor query that made it exit non-zero was removed by SYS-07; only SYS-06 (#7) fixes that. ~~And `save_sitemaps` still swallows a failed `COMMIT` and returns phantom IDs.~~ **Fixed 2026-09-16 (SYS-13, #32):** the try/except around `session.commit()` is gone; a failed commit now propagates through `get_session()`. → [2026-09-16 verification](#2026-09-16--does-re-raising-in-get_session-make-a-db-outage-visible-sys-03) · [2026-09-16 re-audit](#2026-09-16--qa-re-audit-is-a-db-outage-still-loud-after-sys-07-and-what-about-the-commit-path-sys-03) · [2026-09-16 SYS-13/14/DBT-07 fix verification](#2026-09-16--sys-13-sys-14-dbt-07-fix-verification)
- **`task=all` re-fetches every URL the sitemap lists, every run, and duplicates their `articles` rows** (since SYS-07 removed the date gate — `crawl_website("all")` passes the full `save_sitemaps` result into `crawl_newsdetails(specific_sitemaps=…)`, bypassing the no-article/cooldown filter). Until SYS-07 (#8, reopened) lands, run `sitemap` + `full_text` as separate tasks instead of `all`. ~~`articles.sitemap_id` has no unique index.~~ **Fixed 2026-09-16 (DBT-07, #34):** `articles_sitemap_id_uq` unique index + `save_newsdetails` now upserts (`ON CONFLICT (sitemap_id) DO NOTHING`) — a re-crawl no longer creates a second row, though `task=all` itself still wastes a crawl per re-listed URL until SYS-07 is fixed. → [2026-09-16 re-audit](#2026-09-16--qa-re-audit-does-taskall-re-crawl-already-articled-sitemaps-now-that-the-date-gate-is-gone-sys-07) · [2026-09-16 SYS-13/14/DBT-07 fix verification](#2026-09-16--sys-13-sys-14-dbt-07-fix-verification)
- **A 200 status is not proof the page is the article.** emitennews.com 307-redirects missing/unpublished articles to `/404`, which returns HTTP 200 with the home page; trafilatura "extracts" the ticker tape (1.4 k chars, passes the semantic filter). **Fixed 2026-09-16 (SYS-14, #33):** `get_soup` now rejects a 200 whose final `response.url`/`history` or `<link rel=canonical>` matches an error-page pattern (`/404`, `/not-found`, `/error`). Still run `scripts/experiments/probe_soft404.py --website X` before trusting a health-check `ok`, since the pattern-match is necessarily a heuristic. → SYS-14 (#33) · [2026-09-16 re-audit](#2026-09-16--qa-re-audit-emitennews-serves-its-home-page-with-http-200-for-missing-articles-src-01) · [2026-09-16 SYS-13/14/DBT-07 fix verification](#2026-09-16--sys-13-sys-14-dbt-07-fix-verification)
- **EMITENNEWS article pages carry no machine-readable date** (no `datePublished`, `<time>`, or date meta), so `<lastmod>` cannot be cross-checked against publication date from the page. Don't try; watch `sitemaps` for duplicate links per source instead. → same entry
- **The integration suite needs a clean `newsaggregator_test`.** Tests commit fixture rows they never delete; after a few months DS01/DS11 fail on leftovers and the backfill cleanup hits an FK violation. Truncate the test DB (guarded on `current_database()`) before trusting a red run. `test_backfill_pipeline.py` is additionally blocked by SYS-10 (#28) — `scripts/backfill_chunks.py`'s own `EMBEDDING_MODEL=nomic-embed-text` 401s against HF instead of using the pipeline's `EMBEDDING_MODEL_HF`. → same entry · DBT-06 (#29) · SYS-10 (#28)
- ~~A missed crawl run cannot be backfilled from the sitemap because of the pre-dedup date gate.~~ **Fixed 2026-09-16 (SYS-07), then reopened the same day:** the gate is gone; `save_sitemaps`' `(link, posted_at)` dedup is the only filter, so re-listed older entries are inserted — but the gate was also what kept `task=all` from re-crawling everything (see the `task=all` trap above). `backfill_missing_articles.py` still only re-crawls sitemaps already in the DB — to recover a missed *sitemap* window, just run the sitemap task while the site still lists it. → [2026-09-16 verification](#2026-09-16--does-removing-the-date-gate-unblock-emitennews-and-backfills-sys-07)
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
- **Conclusion / do not repeat:** the set of broken outlets changed since June (BISNIS newly 403; ERAID, INVESTORID, KONTAN, MEDIAINDONESIA, TRIBUN recovered on their own — likely sitemap CDN flakiness at the time). "OK" ≠ "site extractor works". The check must be scheduled and must distinguish fallback rescues (#9, OPS-02 (#10)).
- **Links:** `AUDIT_2026-09-15.md`, tracker tracker (#25).

### 2026-09-15 — User-Agent is not why sitemaps fail
- **Question / hypothesis:** the page loader still sends a 2017 `Chrome/56` UA; maybe bot protection is blocking the sitemap fetches.
- **Method:** `scripts/experiments/probe_sitemap_ua.py` — every `URL` enum value fetched with the default headers and with a modern Chrome/128 UA; status, size, content-type compared.
- **Result:** identical status codes for all 32. Non-200s: ANTARANEWS 404 (URL is an *English sports RSS feed*), BATAMPOS 404, KAPANLAGI 404, TIRTO 404, REQNEWS 404 (unused), BISNIS 403 (5 KB HTML challenge page), IDNTIMES 403 (empty body), INEWS `SSLError: CERTIFICATE_VERIFY_FAILED`. BERITASATU returns `application/rss+xml` but its crawler handles it.
- **Conclusion / do not repeat:** don't spend time on UA rotation for the sitemap layer. For BISNIS/IDNTIMES the options are another endpoint (RSS, `/robots.txt` Sitemap lines), richer headers (`Referer`, `Accept-Language: id-ID`, `Sec-Fetch-*`) — untested — or the headless loader. Re-run the probe after any header change to see if it moved the needle.
- **Links:** SRC-02 (#13), SRC-03 (#14), SRC-04 (#15).

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
- **Conclusion / do not repeat:** all confirmed; filed as SYS-01 (#2), SYS-05 (#6), SYS-07 (#8), DBT-01 (#20). These snippets should become the regression tests when each is fixed.
- **Links:** `AUDIT_2026-09-15.md` SYS-01/05/07, DBT-01.

### 2026-09-15 — Read production `crawl_log` to see how long sources have been dead
- **Question / hypothesis:** can the DB tell us when each source stopped producing articles?
- **Method:** read-only SQL over `crawl_log` and `sitemaps LEFT JOIN articles` via `SQLAlchemyClient`.
- **Result:** Postgres was not running (`connection refused` on 5431). The script printed its first header and continued silently — `get_session()` swallowed the `OperationalError`.
- **Conclusion / do not repeat:** inconclusive on the original question — **still to do once the DB is up** (first step of SYS-04 (#5)). Incidentally proved SYS-03 (#4) live: a DB outage looks like success.
- **Links:** SYS-03 (#4), SYS-04 (#5).

### 2026-09-16 — Production `crawl_log` and per-source gaps (follow-up to the 2026-09-15 attempt)
- **Question / hypothesis:** how long has each source been dead, and do the audit's silent-failure signatures show up in real data?
- **Method:** Postgres up (Docker). Read-only SQL: last 12 `crawl_log` rows; `article_count` distribution for `task='full_text'`; per source `sitemaps LEFT JOIN articles` counting `attempted_no_article` (`last_crawl_attempt IS NOT NULL`) vs `never_attempted`; duplicate `(sources, link)` rows.
- **Result:**
  - Last activity anywhere: **2026-06-03**. Last 12 `crawl_log` rows are all EMITENNEWS on 2026-06-02, final one `failed: argument of type 'NoneType' is not iterable` → SRC-01 (#12) in production. 4 rows stuck at `started` (process died without `log_crawl_failed`).
  - `full_text`: 107 `completed`, max `article_count` = **0** → SYS-04 (#5).
  - KUMPARAN 988 sitemaps / **988 attempted, 0 articles** → SYS-01 (#2)'s signature (`[]` → no fallback → stamped attempted). OKEZONE 1,020 sitemaps / **0 attempted, 0 articles** → SYS-02 (#3)'s signature (crash → `None` → never stamped).
  - **VIVA 39,262 sitemaps / 37,381 attempted / 0 articles** although `check_crawlers.py` shows VIVA extracting fine (2/2, 2,444 chars). Unexplained — filed as SYS-08 (#26).
  - MEDIAINDONESIA 12,482 / 96 articles / 10,898 never attempted: serial (non-parallel) crawl + 1,000/run limit = permanent backlog, not a bug per se.
  - Duplicate links: only 2 rows total (EMITENNEWS's `posted_at=now()` hasn't bitten because it never saved anything).
- **Conclusion / do not repeat:** the pipeline has produced nothing for 3.5 months because the only enabled source crashes. The per-source `attempted_no_article` vs `never_attempted` split is a reliable fingerprint for "fallback skipped" vs "extractor crashes" — reuse it when triaging. Re-run this query after SYS-01 (#2) and SYS-02 (#3) land; VIVA needs its own investigation.
- **Links:** SYS-01 (#2), SYS-02 (#3), SYS-04 (#5), SRC-01 (#12), SYS-08 (#26).

### 2026-09-16 — Is the orphaned worktree branch still needed?
- **Question / hypothesis:** `worktree-phase1-migration` (1 commit, 5 uncommitted edits, 3 untracked files) might contain work not in `dev`.
- **Method:** `git diff --name-only dev worktree-phase1-migration` + per-file diff of the worktree's uncommitted edits against main; copied its `tests/unit/test_chunker.py` into main and ran pytest.
- **Result:** every committed file already present in main in a newer form. Uncommitted edits were older versions of the sitemap datasource / `table.py`. `test_chunker.py` failed at collection: `ImportError: cannot import name '_MIN_TOKENS' from 'newscrawler.core.chunker'` (API since rewritten). Only unique asset: `scripts/migrate_posted_at.sql`.
- **Conclusion / do not repeat:** superseded; worktree removed, branch deleted (recoverable via `git branch worktree-phase1-migration 0050e91`), migration carried over. Don't re-examine it.
- **Links:** commit `9b08107`.

### 2026-09-16 — Does the SYS-01 (#2) fallback fix rescue KUMPARAN live?
- **Question / hypothesis:** with `_has_usable_text()` gating the fallback chain (empty **or** < `MIN_ARTICLE_CHARS`), KUMPARAN — whose `span[data-qa-id=story-paragraph]` selector is dead and returns `[]` — should move from PARTIAL to OK via trafilatura. OKEZONE should *not* move (its extractor raises; that's SYS-02 (#3)).
- **Method:** 12 new unit tests in `tests/unit/test_crawler_base.py::TestExtractionFallback` / `TestHasUsableText` (trafilatura and newspaper patched); then live `venv\Scripts\python.exe scripts/check_crawlers.py --website KUMPARAN,OKEZONE --sample-size 3`.
- **Result:** unit suite 145 passed. Live: `KUMPARAN OK 100 links, 3/3 (9899ch)` — every sample logged `Standard extraction failed … Trafilatura extraction successful`. `OKEZONE PARTIAL 0/3` with `'NoneType' object has no attribute 'find'` on each, unchanged as predicted.
- **Conclusion / do not repeat:** the fix is confirmed against a real broken layout. KUMPARAN is now "OK by fallback" — its selector is still dead, so it will show as FALLBACK once OPS-02 (#10) lands and should get a selector refresh or be declared trafilatura-first (#18). The newspaper fallback is now also wrapped in try/except, so a `download()` failure no longer discards the whole article. Next: SYS-02 (#3) for the OKEZONE-style crash.
- **Links:** SYS-01 (#2) (fixed), SYS-02 (#3), OPS-02 (#10), SRC-07 (#18); commit below.

### 2026-09-16 — Does catching extractor crashes rescue OKEZONE live? (SYS-02)
- **Question / hypothesis:** OKEZONE's `_get_text` does `soup.find(...).find(...)` on a container that no longer exists → `AttributeError` → the outer `except BaseException` returned `None`, so the article was discarded *and* never marked attempted. Wrapping `_get_reporter_from_text` and `_get_whole_text` individually should turn the crash into "extractor failed" and let trafilatura take over.
- **Method:** 4 new unit tests in `tests/unit/test_crawler_base.py::TestExtractorCrashFallsThrough` (body raises / reporter raises / both / warning logged); live `check_crawlers.py --website OKEZONE --sample-size 3`.
- **Result:** unit suite 149 passed. Live: `OKEZONE OK 100 links, 3/3 (4047ch)` — each sample logged `WARNING Site extractor raised … AttributeError` then `Trafilatura extraction successful`. Before: `PARTIAL 0/3`.
- **Conclusion / do not repeat:** confirmed. Both PARTIAL outlets from the audit are now OK-by-fallback (KUMPARAN via SYS-01, OKEZONE via SYS-02); their selectors are still dead → SRC-07 (#18). Residual: a *fetch* failure (`get_soup` → `None`) still returns `None` and is re-fetched every run — split out as SYS-09 (#27) because it needs a cooldown/failure-count column, not a crawler change. Note OKEZONE's first sitemap branch still serves 2025-08 articles; that's SRC-07's branch-selection point.
- **Links:** SYS-02 (#3) fixed · SYS-09 (#27) new · SRC-07 (#18).

### 2026-09-16 — Does re-raising in `get_session` make a DB outage visible? (SYS-03)
- **Question / hypothesis:** `SQLAlchemyClient.get_session` caught every exception, rolled back and returned normally, so `save_sitemaps` fell through to `return []` and the crawl logged `completed`. Adding `raise` after the rollback should make the failure propagate to the existing `log_crawl_failed` / per-batch handlers, and make a DB-down startup exit non-zero.
- **Method:** traced all 29 `get_session()` call sites for what catches the propagated error (crawl_log writers, web UI and `check_crawlers --log-db` already wrap; sitemap/article/chunk writes propagate to `crawl_sitemaps`/`crawl_newsdetails` → `log_crawl_failed` + re-raise, or to the per-batch `except` in `_crawl_newsdetails_inner`; `load_last_time_crawling` runs in `init_crawler()` *outside* `process_event`'s try). 5 unit tests (`tests/unit/test_sqlalchemy_client.py`, mocked session) + 3 live tests (`tests/integration/test_sqlalchemy_client_live.py`: bad SQL raises, session reusable afterwards, port-1 client raises `DBAPIError` from `save_chunks`). End-to-end: `POSTGRES_DB_PORT=1 python -c "process_event({'task':'sitemap','website':'KOMPAS'})"`.
- **Result:** unit 178 passed; integration 30 passed / 1 skipped (backfill file excluded, see SYS-10). End-to-end: `ERROR … Database error, rolling back: OperationalError: … port 1 failed: Connection refused`, traceback, **exit code 1**, the post-call print never reached. Baseline integration run *before* the change was `9 failed / 3 errors` for unrelated reasons (leftover fixture rows → DBT-06; `nomic-embed-text` on HF → SYS-10); truncating `newsaggregator_test` gave a clean 27-pass baseline.
- **Conclusion / do not repeat:** confirmed. A DB outage is now loud at every layer that matters. Two things learned the hard way: (1) run the integration suite against a *truncated* test DB or its failures are noise; (2) `scripts/backfill_chunks.py` has been unrunnable since the MiniLM switch — don't use it until SYS-10 lands.
- **Links:** SYS-03 (#4) fixed · SYS-10 (#28), DBT-06 (#29) new · SYS-06 (#7) still needed so `process_event`-level failures mid-run also exit non-zero.

### 2026-09-16 — EMITENNEWS: what does its sitemap actually look like, and does the rewrite hold up? (SRC-01)
- **Question / hypothesis:** the crawler crashed on every run (`TypeError: argument of type 'NoneType' is not iterable`). Suspected `_scrape` passing `<loc>` tags to a `_get_link` that looks for a `<loc>` *inside* them. Also `_get_timestamp` returned `now()`, which would change the `(link, posted_at)` dedup key daily.
- **Method:** fetched the live index and children with `RequestsPageLoader`; inspected tag structure and `<lastmod>` ordering across children 1/2/3/23; checked `DateTimeReader.convert_date('2026-09-16')` and the base class's UTC conversion. Rewrote `_scrape` to iterate `<url>`, read `<lastmod>` (kept in WIB), cap children at `max_child_sitemaps = 2`; 10 offline unit tests (`tests/unit/test_emitennews_crawler.py`); live `check_crawlers.py --website EMITENNEWS --sample-size 3`; then ran the real sitemap crawl into **`newsaggregator_test`** twice via `NewsDataSource.save_sitemap` and counted rows (cleaned up after).
- **Result:**
  - Index = 23 children `sitemap-current-N.xml`, all `lastmod`=today; each child = 1,000 `<url><loc/><lastmod/></url>` (no `news:` tags); **chronological newest-first** (child 1: 2026-09-20→08-24, child 2: 08-24→08-03, child 3: 08-03→07-13). Child 23 has < 2 entries.
  - `convert_date('2026-09-16')` → `2026-09-16 00:00+07:00`; the base `_get_timestamp`'s `.astimezone(UTC)` turns that into `2026-09-15 17:00Z` → stored **20260915**. Filed as SYS-11 (#30) — affects every source for 00:00–06:59 WIB articles.
  - Health: `EMITENNEWS OK 2000 links, 3/3 (2625ch)`. 2 of 3 samples used trafilatura: one is the future-dated stub (`lastmod 2026-09-20`, no `div.news-page-item`), one an awards/event page. The selector works on normal articles (5,198 chars on the third sample).
  - Test-DB double run: run 1 inserted 2,000 rows / 2,000 distinct links (posted_at 2026-08-03..09-20); run 2 → still 2,000 rows, **no duplicates** ✔ — but `date-gate passed 0/2000`: `NewsDataSource.save_sitemap` dropped every row before dedup because max posted_at is now the future-dated 2026-09-20.
- **Conclusion / do not repeat:** SRC-01's own criteria pass. **SYS-07 (#8) is a hard blocker for EMITENNEWS after its first run** — with date-only timestamps and a future-dated stub, the pre-dedup gate discards everything until the calendar passes 2026-09-20, and even then same-day articles. Fix SYS-07 before the next scheduled crawl. Don't raise `max_child_sitemaps` for the daily crawl; use `None` only for a one-off backfill. `?page=all` is harmless on emitennews.com.
- **Links:** SRC-01 (#12) fixed · SYS-07 (#8) now urgent · SYS-11 (#30) new.

### 2026-09-16 — Re-audit of the four P0 fixes (SYS-01/02/03, SRC-01)
- **Question / hypothesis:** did today's fixes introduce anything, or miss a path? Re-read each diff and probed the interactions between them.
- **Method:** three targeted repros: (A) extractor raises + trafilatura and newspaper both empty; (B) `CrawlerAPI.crawl_websites_in_batch` with a service that raises on source 1 of 5; (C) re-read `KnowledgeExtractor.extract_all` / `NewsletterGenerator.generate` for per-item handling now that `get_session` re-raises; (D) grep of every site extractor for non-string list items (would break `_text_length`).
- **Result:** (A) **miss** — `extracted_text=None` → `NewsDetailsDTO` validation error (`List[str]`) → `_get_news_details` returns `None` → never marked attempted. SYS-02's tests only covered "trafilatura succeeds". (B) **pre-existing bug** — only `['BERITASATU']` attempted, 4 skipped, exception escapes; SRC-01 (21 sources) and SYS-03 (DB errors propagate) both raised its blast radius today. (C) extractor has a per-article `try/except`; newsletter `save_digest` is wrapped; no regression. (D) none found. Trade-off noted on SYS-01: `MIN_ARTICLE_CHARS=200` + "keep the longer" can let boilerplate-laden trafilatura output beat clean short site text.
- **Conclusion / do not repeat:** when a fix's purpose is "the sitemap gets marked attempted", the test must cover the *all-fallbacks-fail* branch, not just the rescue branch. Any change that makes errors propagate (SYS-03-style) needs the enclosing loops checked for per-item isolation — `crawl_websites_in_batch` had none. Reopened SYS-02; filed SYS-12 (#31).
- **Links:** SYS-02 (#3) reopened · SYS-12 (#31) new · SYS-01 (#2) comment.

### 2026-09-16 — Does per-source isolation keep a batch alive past a failing source? (SYS-12)
- **Question / hypothesis:** with a `try/except` per source in `CrawlerAPI.crawl_websites_in_batch`, a raising source should be logged and skipped, the rest should run, and one `RuntimeError` should surface at the end.
- **Method:** 7 unit tests (`tests/unit/test_crawler_api.py`); end-to-end `process_event({'task':'sitemap','website':'KOMPAS,BOGUS,IDXCHANNEL'})` against `newsaggregator_test` (BOGUS is not in `CRAWLER_DICT` → `AttributeError` inside `crawl_sitemaps`). First attempt used SUARA as the "broken" source — it doesn't raise: `URL.SUARA == ""` → `get_soup("")` → `None` → 0 links → `completed`. A silent zero, not an exception (SRC-02 / SYS-04 territory).
- **Result:** unit 177 passed. End-to-end: `ERROR BOGUS failed (sitemap): AttributeError …` → `Saved 129 sitemaps` for IDXCHANNEL → `Batch 'sitemap' finished: ok=2 failed=1 | failed: BOGUS (…)` → `crawl_log`: KOMPAS completed, BOGUS failed, IDXCHANNEL completed. `process_event` still logs the final error at INFO and exits 0 — that's SYS-06 (#7).
- **Conclusion / do not repeat:** confirmed. Note for future "does source X fail?" checks: a dead/empty sitemap URL is *not* an exception path — it shows up only as `article_count=0`/0 links, so use `check_crawlers.py`, not the crawl log, to detect it until OPS-02 lands.
- **Links:** SYS-12 (#31) fixed · SYS-06 (#7) next for the exit code.

### 2026-09-16 — Does removing the date gate unblock EMITENNEWS and backfills? (SYS-07)
- **Question / hypothesis:** `NewsDataSource.save_sitemap` dropped any entry not strictly newer than the stored max `posted_at` for its (source, category), *before* `save_sitemaps`' `(link, posted_at)` dedup. Removing it should (a) let older never-seen entries in, (b) let date-only sources keep accumulating after run 1, and (c) not create duplicates because the dedup already handles re-listed links.
- **Method:** deleted the gate; stopped eager-loading `last_time_crawling` in `SQLAlchemySitemapDataSource.__init__` (full-table `GROUP BY` at every start; crashes on a NULL max); scoped the dedup pre-fetch to the batch's own `sources` since a batch can now span weeks. 4 unit tests (`tests/unit/test_news_data_source.py`, the audit repro), 3 live (`tests/integration/test_sitemap_backfill_live.py`: older-after-newer inserted, same batch twice = no dups, EMITENNEWS-style consecutive days). Re-ran the morning's EMITENNEWS double-run into `newsaggregator_test`, plus a run 3 adding one article dated *before* the future-dated stub.
- **Result:** unit 181 / integration 34 passed. EMITENNEWS: run 1 `2000/2000 → 2000 rows`; run 2 `2000/2000 → 2000 rows` (this morning: `0/2000`); run 3 `2001/2001 → 2001 rows` — the new pre-stub article is inserted. Distinct links == rows throughout.
- **Conclusion / do not repeat:** confirmed; EMITENNEWS is now viable across runs. The dedup pre-fetch is now `WHERE sources IN (batch) AND posted_at >= earliest` — for a 6-week EMITENNEWS batch that's that source's rows only, not every source's. `load_last_time_crawling()` still exists (DS08/DS09 guard it) but nothing in the crawl path calls it.
- **Links:** SYS-07 (#8) fixed · SRC-01 (#12) now truly done · SYS-11 (#30) still applies to timestamped sources.

### 2026-09-16 — QA re-audit: does `task=all` re-crawl already-articled sitemaps now that the date gate is gone? (SYS-07)
- **Question / hypothesis:** the removed gate only let strictly-newer entries through, so `crawl_sitemaps`' return value used to be ≈ "new since last run". Post-244d9de `save_sitemaps` returns *every* entry with an ID, and `crawl_website("all")` hands that list to `crawl_newsdetails(specific_sitemaps=…)`, which never consults `load_all_sitemaps`' no-article/cooldown filter. Suspected: every listed URL is re-fetched per run and re-saved as a new `articles` row.
- **Method:** real `NewsDataSource` against `newsaggregator_test` (env forced), no network: 3 synthetic `REAUDIT07` entries → `save_sitemap` → `save_newsdetails` for each returned ID (simulating step 2) → `save_sitemap` again with the same batch → compare with `load_sitemap` → `save_newsdetails` again. Cleaned up after. Schema check with `pg_constraint`/`pg_indexes`.
- **Result:**
  ```
  run 1: save_sitemap returned 3 ids [2048, 2049, 2050]        articles after run 1: 3
  run 2: save_sitemap returned 3 ids [2048, 2049, 2050]        load_sitemap (filtered path) would return 0
  articles after run 2: 6 for 3 distinct sitemaps
  ```
  `articles` has only `articles_pk` + `articles_sitemap_fk` — no unique on `sitemap_id`. Production already: 12,506 rows / 11,889 distinct `sitemap_id` (617 extra over 437 sitemaps, max 4 copies; GRIDID +196, JPNN +122, PIKIRANRAKYAT +102 …) from the older `delta.seconds > 0` loophole. Also: `crawl_log.article_count` for `task='sitemap'` now records entries listed, not rows inserted.
- **Conclusion / do not repeat:** SYS-07 reopened — the fix is correct for `sitemaps` but regresses `task=all`, the `__main__.py` default. Recommended fix: `task=all` should call `crawl_newsdetails(website_name)` with no `specific_sitemaps` (the code comment already claims it loads from the DB), which gives cooldown + no-article + 1,000-limit semantics for free. Lesson: when a filter is removed, grep for who consumed its *output* — here the gate doubled as the "what to crawl next" selector. Filed DBT-07 for the unique index (the safety net that would have made this loud).
- **Links:** SYS-07 (#8) reopened · DBT-07 (#34) new · SYS-13 (#32) related.

### 2026-09-16 — QA re-audit: is a DB outage still loud after SYS-07, and what about the commit path? (SYS-03)
- **Question / hypothesis:** SYS-03's closing note said "DB-down at startup exits non-zero" because `SQLAlchemySitemapDataSource.__init__` queried the DB inside `init_crawler()`, outside `process_event`'s try. SYS-07 removed that query. Does the done-when still hold? And is `save_sitemaps`' own `try/except` around `session.commit()` a swallow of the same class?
- **Method:** (a) `POSTGRES_DB_PORT=1`, `Crawler.get_news_in_bulk` patched to return one fake KOMPAS entry, `process_event({'task':'sitemap','website':'KOMPAS'})`, exit code captured. (b) mocked session whose `commit()` raises `OperationalError`, real `SQLAlchemySitemapDataSource.save_sitemaps` with 3 entries.
- **Result:** (a) `ERROR Database error, rolling back: OperationalError … port 1 … Connection refused` + traceback → `ERROR KOMPAS failed (sitemap)` (SYS-12) → `Batch 'sitemap' finished: ok=0 failed=1` → `INFO Failed to process task 'sitemap'. Reason: 1 of 1 sources failed` → **exit code 0**. `crawl_log` cannot be written at all in this state. (b) `ERROR Critical commit error: … [SQL: COMMIT]` then `RETURNED NORMALLY: 3 sitemaps with ids [101, 102, 103]` — the caller logs `Saved 3 sitemaps`, marks `crawl_log` completed, and (under `task=all`) crawls articles against IDs that were rolled back; FAISS would keep orphan vectors because the index is written before the SQL FK fails.
- **Conclusion / do not repeat:** SYS-03 stays closed — the re-raise is intact and the outage is loud in the log — but the "exits non-zero" claim is void; SYS-06 (#7) is now the *only* guard against a green scheduler run during an outage (commented there). The commit swallow is SYS-13 (#32). Rule for future call-site audits: look for `try/except` around `commit()` inside the `with get_session()` block, not just around the block.
- **Links:** SYS-03 (#4) comment · SYS-06 (#7) comment · SYS-13 (#32) new.

### 2026-09-16 — QA re-audit: EMITENNEWS serves its home page with HTTP 200 for missing articles (SRC-01)
- **Question / hypothesis:** `check_crawlers.py --website EMITENNEWS,KUMPARAN,OKEZONE --sample-size 3` → all three `OK 3/3`, but EMITENNEWS's `sehatkan-keuangan-ptpp-…` (a normal-looking slug) fell to trafilatura. Is the selector flaky, or is the page not an article?
- **Method:** fetched the URL with/without `?page=all` and a nonsense slug via `requests` with the project headers, printing `status`, `history`, final URL, `<link rel=canonical>`, `div.news-page-item` count. Then ran the real `_get_news_details` on it and fed the DTO to `SemanticImportanceFilter`. Rate check: first 15 + 25 random entries from the 2 child sitemaps; then the new reusable `scripts/experiments/probe_soft404.py --website EMITENNEWS --sample 30`. Selector quality: 30 random articles, site-selector vs trafilatura char counts, paragraph dump for one.
- **Result:** every missing slug → `200 hist=[307] final=https://www.emitennews.com/404 canonical=…/404`, title `Emitennews.com - Berita Emiten, Saham dan Investasi`, 184 `<p>`, no `news-page-item`. `_get_news_details` → DTO with 1 paragraph / 1,377 chars = the home-page index ticker (`IDXINDUST 1.03% IDXINFRA -0.22% …`); `is_important -> True`. Soft-404s: 2/40 in the first probe (the `lastmod 2026-09-20` unpublished stub + the awards page, both among the 15 newest), 0/30 random. Selector: 30/30 real articles extracted 1.9–22.9 k chars of distinct paragraphs; trafilatura returned ~40 % of the body (e.g. 3,121 vs 1,569 chars) — the selector is the better primary. `lastmod` vs publication date: **inconclusive** — article pages have no `datePublished`, `<time>` or date meta at all (12/12 sampled).
- **Conclusion / do not repeat:** SRC-01 stays closed; the crawler is right. The pipeline-level hole is `get_soup` accepting any 200 without looking at `response.url`/`history` → SYS-14 (#33); combined with SYS-01's "≥ 200 chars is usable" it saves ticker tape as an article body, and the newest-first queue fetches exactly these not-yet-published entries first. Run `probe_soft404.py` on the other healthy outlets before assuming this is EMITENNEWS-only. Don't try to verify EMITENNEWS dates from the article HTML.
- **Links:** SRC-01 (#12) comment · SYS-14 (#33) new · OPS-02 (#10) (health check counts these as `ok`) · `scripts/experiments/probe_soft404.py`.

### 2026-09-16 — QA re-audit of SYS-01, SYS-02, SYS-12 (no findings)
- **Question / hypothesis:** do the three remaining closed fixes hold up beyond their own tests?
- **Method:** SYS-01/02 — re-read `crawler.py:187-286`; checked all 32 `_get_whole_text` return shapes (list-of-str / `None` / KONTAN `str`) against `_text_length`; live health check (above); probed the "empty DTO whose title passes the filter" path through `HierarchicalChunker.chunk()`. SYS-12 — exercised the isolation with a real exception class (DB outage, see the SYS-03 entry) instead of a bogus source name; checked the `str(e).splitlines()[0]` guard and that `KeyboardInterrupt` is not caught.
- **Result:** KUMPARAN `OK 3/3 (2201ch)` and OKEZONE `OK 3/3 (4047ch)` via trafilatura as claimed; KONTAN's `str` is wrapped to `[str]` at `crawler.py:230` so no non-string item reaches `_text_length`; empty-text DTO → 0 chunks, nothing raised, sitemap still marked attempted. SYS-12: `ok=0 failed=1`, single `RuntimeError` surfaced, traceback logged.
- **Conclusion / do not repeat:** all three stay closed. Unit suite 177 passed, integration 33 passed / 1 skipped (backfill file excluded per SYS-10) at `244d9de`.
- **Links:** SYS-01 (#2), SYS-02 (#3), SYS-12 (#31) comments.

### 2026-09-16 — SYS-13/SYS-14/DBT-07 fix verification
- **Question / hypothesis:** do the proposed fixes for the three newly-raised tickets actually close them, and does DBT-07's dedup migration handle the `entity_mentions.article_id` FK correctly (the ticket text only mentions `entity_mentions.sitemap_id` surviving, but `entity_mentions` also hard-FKs `articles.articles_id`)?
- **Method:** SYS-13 — removed the `try/except` around `session.commit()` in `save_sitemaps`; mocked-session unit tests assert a failing commit propagates and rolls back via `get_session()`. SYS-14 — added a redirect/canonical check to `get_soup` (`ERROR_PATH_PATTERN` matching `/404`, `/not-found`, `/error`, same as `probe_soft404.py`); unit tests patch `get_url` with fake responses (redirect-to-404, in-place error page via canonical, legit redirect to a real path). DBT-07 — wrote `scripts/migrate_articles_unique_sitemap.sql` (rank duplicates: entity_mentions-referenced row first, then `knowledge_extracted=1`, then lowest `articles_id`; abort via `RAISE EXCEPTION` if two duplicates for one sitemap are both referenced by `entity_mentions`) and switched `save_newsdetails` to `INSERT ... ON CONFLICT (sitemap_id) DO NOTHING`; added `unique=True` to the ORM column. Ran the migration directly against `newsaggregator_test` (psql isn't on PATH in this shell, used psycopg2) with three synthetic scenarios: (A) plain duplicates, no entity_mentions; (B) one duplicate referenced by entity_mentions but not the lowest id / not knowledge_extracted; (C) two duplicates for the same sitemap both referenced by entity_mentions (the abort case). Verified `save_newsdetails` idempotency end-to-end against the same test DB, then cleaned up every row the verification created.
- **Result:** first migration draft had a `GroupingError` (`SELECT em.article_id ... GROUP BY a.sitemap_id` — selected a non-grouped column instead of `a.sitemap_id`); fixed before it touched real data. After the fix: scenario C aborted with `DBT-07: 1 sitemap_id(s) have entity_mentions referencing more than one duplicate articles row` and changed nothing; scenario A+B together went from 14→11 rows, scenario A kept the `knowledge_extracted=1` row, scenario B kept the entity_mentions-referenced row (no FK violation); final state back to the original 8/8. `save_newsdetails` called twice for the same `sitemap_id` left exactly 1 row. Full unit suite: 191 passed (23 new). `tests/integration` has 10 pre-existing failures unrelated to these fixes — traced to already-tracked DBT-06 (#29, uncommitted fixture rows breaking DS01/backfill cleanup) and SYS-10 (#28, `scripts/backfill_chunks.py` embeds with `nomic-embed-text`/768-dim instead of the pipeline's `EMBEDDING_MODEL_HF`, 401s against a gated HF model). Filed a duplicate of SYS-10 (DBT-08, #35) before noticing the existing ticket — closed it as a dup immediately after.
- **Conclusion / do not repeat:** the ticket's own suggested dedup rule ("keep lowest articles_id, entity_mentions/knowledge_extracted survive because they key off sitemap_id") undersells the risk — `entity_mentions.article_id` is a real FK to `articles.articles_id`, so a naive lowest-id dedup can throw a `ForeignKeyViolation` mid-migration. Always rank duplicate-row survivors by "is this row FK-referenced elsewhere" before falling back to an arbitrary tie-break, and add a pre-flight abort for the case where two duplicates are both referenced (don't guess). Confirmed `articles_sitemap_id_uq` now exists on `newsaggregator_test` — a fresh `newsaggregator` (prod) run of `scripts/migrate_articles_unique_sitemap.sql` is still needed and wasn't done here (out of scope — no prod access from this session).
- **Links:** SYS-13 (#32) fixed · SYS-14 (#33) fixed · DBT-07 (#34) fixed · DBT-06 (#29) hit, not fixed · SYS-10 (#28) hit, not fixed · `scripts/migrate_articles_unique_sitemap.sql`, `tests/unit/test_save_sitemaps_commit.py`, `tests/unit/test_soft404_detection.py`, `tests/unit/test_save_newsdetails_upsert.py`, `tests/integration/test_save_newsdetails_idempotent.py`.
