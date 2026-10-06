# RAG search redesign: implementation approach (2026-10-07)

## The tricky parts
1. **Citation parsing.** Models write `[2]`, `[1][3]`, `[1, 3]`, `[1-3]`, and sometimes `[KONTAN]`.
   - Accept `\[\d+(\s*[,–-]\s*\d+)*\]`. A range expands only when it is ascending and short (<= 5).
   - Every number in range becomes a citation segment. A bracket with any out-of-range number stays plain text in full, so the reader never sees a half-linked `[2, 9]`.
   - Anything else in brackets is text.
2. **Markdown cleanup before parsing:**
   - drop `**`/`__` emphasis and leading `#` headings;
   - turn a leading `* ` / `• ` / `1. ` into `- `;
   - drop backticks.
   - Never touch `[n]`.
3. **Number check corpus:**
   - The corpus is the cited cards (all cards when none are cited). Each card contributes the same header line the model saw (`Outlet · Hari, d Mmm yyyy · judul`), its lead and its snippet, plus today's line.
   - `[n]` markers are removed from the answer before checking, otherwise "2" from `[2]` must be in the source.
   - The fixed "not enough" sentence has no numbers.
4. **History:** pass the last 3 ok turns with `[n]` stripped. The previous turn's numbering means nothing to the new article list.
5. **DB metadata before filtering:**
   - One query: `sitemaps s LEFT JOIN articles a USING sitemap_id LEFT JOIN chunks l1 ON level=1`, `WHERE s.sitemap_id = ANY(:ids)`. L1 is <= 1 row per sitemap (measured: max 1).
   - A hit whose sitemap has no row is dropped (its vector points at nothing).
   - The FAISS metadata only fills in when the query fails.
6. **FTS filters:** fixed SQL fragments chosen by which filters are set; values are only ever bind parameters.
7. **Session id out-of-band:** the turn fragment carries `<input type="hidden" id="session-id" name="session_id" value="…" hx-swap-oob="true">`, which replaces the input inside the follow-up form. The main form has no `session_id`, so it always starts fresh.
8. **Two-step answer placeholder:**
   - `<div class="answer pending" hx-post="/api/answer/{id}" hx-trigger="load" hx-swap="outerHTML" role="status">`.
   - The "Coba lagi" button is a form with the same `hx-post`, targeting `closest .answer`.
   - The answer route pops the turn only on a final state (`ok` / `unavailable`); `failed` keeps it for the retry.
9. **Warm-up:**
   - A FastAPI `lifespan` starts a daemon thread: `_get_processor()`, then `search_l2("pemanasan", k=1)`. The time is logged.
   - Unit tests never enter the lifespan (TestClient without `with`), and `RAG_WARM_AT_STARTUP=0` disables it explicitly.
10. **Topic/portal display:** `SECTION_NAMES[topic]` and `outlet(source)`. An unknown topic shows no chip.

## Files touched
- **New:** `core/web_copy.py`, `web/answer.py`, `web/filters.py`, `web/turn_store.py`, `web/site_stats.py`, `web/templates/_turn.html`, `_answer.html`, `_sources.html`, `web/static/htmx.min.js`.
- **Changed:** `core/summarizer.py`, `core/constants.py`, `web/query_processor.py`, `web/app.py`, `web/templates/index.html`, `web/static/style.css`; `result_fragment.html` is deleted.
- **Tests:** see the staff-engineer table. The existing tests in `test_query_processor_ranking.py`, `test_web_app_concurrency.py` and `test_api_health_degraded.py` are adapted to the new `QueryProcessor` constructor.
