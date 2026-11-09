# Design: SRC-59, DBT-60, SYS-91 (2026-10-12 night)

**Approved:** owner, 2026-10-12. SYS-91's `--apply` may run at ~06:00 on 10-13, before the 07:00 crawl, after a backup.
**No ADR:** none of the three changes the architecture.
- SRC-59 changes one source's sitemap URL.
- DBT-60 tightens a validator.
- SYS-91 is a data repair through the existing store_repair toolkit (ADR-015).

## Pre-design probe (2026-10-12 ~21:10 WIB, light requests)
- `sitemap_news.xml` returns 404.
- With the browser UA (investor.id is already in `BROWSER_UA_HOSTS`), `sitemap.xml` returns 200 and is an index listing `sitemap_basic.xml`, `sitemap_post.xml` and `sitemap_news.xml`.
- `sitemap_post.xml` returns 200: 100 `<url>` entries, `lastmod` only, no `news:` tags. The lastmods span 10:33-22:10 today; `?page=2` returns the same 100.
- With our bot UA every investor.id URL is 403 (CloudFront). Production uses the browser UA, so this does not apply.
- The latest 100 entries by section: market 32, business 29, national 9, macroeconomy 9, money-lab 8, international 5, lifestyle 4, finance 2, investory 2.

## SRC-59: INVESTORID from sitemap_post.xml (P2)
- `URL.INVESTORID` becomes `https://investor.id/sitemap.xml`.
- `_get_branches(soup)`: `{"news": <loc>}` for the `<loc>` that `re.match`es `^https://investor\.id/sitemap_post\.xml$`, else `{}`. `sitemap_news.xml` and `sitemap_basic.xml` are never keyed.
- An empty index result makes the run `failed` with a reason (OPS-35).
- The branch key stays `news`, as before, so stored categories are continuous and the probe decides each article.
- lastmod-only entries take the existing SYS-32 path: a slug placeholder, then the page title.
- Accepted limit: the 100-entry window (about 12 h) can miss posts on busy days. The old news sitemap had the same 100 cap.
- Per-URL section categories (lifestyle) are SRC-47's scope.
- Verify: unit test of `_get_branches` on the probed index, and `check_crawlers.py --website INVESTORID` with `--report-dir` in the scratchpad.

## DBT-60: one date rule for stored yyyymmdd (P3)
- `posted_at_datetime` returns midnight of that day for an int, an integral float, or an 8-digit `str` (after stripping) holding a valid yyyymmdd in range.
- It raises `ValueError` for any other int, float or digits-only string: Unix seconds are never accepted.
- A non-numeric string (ISO dates) or a datetime passes through to pydantic unchanged. None stays None. A bool passes through, as today.
- Tests: the ticket's three forms, out-of-range numbers, an invalid month, ISO strings unchanged, plus mutants.

## SYS-91: search-index dates = sitemaps.posted_at (P3)
- **Reader impact today:** none on the normal path. `_attach_metadata` takes `posted_at` from the DB (SYS-92); the FAISS value is used only when that query fails. The repair is data hygiene, and it meets the ticket's Done-when.
- **`scripts/repair_faiss_posted_at.py`:**
  - the dry run (default) loads both indexes (`load_index`, `NoEmbeddings`), compares every document's `metadata['posted_at']` with `sitemaps.posted_at` of its sitemap, and reports mismatches by source and kind (`19xx`, empty, other);
  - `--apply` holds the run lock, refuses while a crawl runs (`crawl_running`), backs up through `store_repair.backup`, rewrites the metadata in place, and saves through `ChunkFAISSDatasource._atomic_save_local` (generation-checked). It does not re-embed. A second run finds 0.
  - `--only-1970` (default on) limits the targets to the ticket's `19xx` documents. Widening the scope needs the owner, after reading the dry run.
- Tests: pure target selection (unit); a temp-FAISS integration test (write, rerun finds 0, dry run writes nothing); a `test_run_lock` write path.
