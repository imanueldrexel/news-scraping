# RAG search redesign: what was built (SDE, 2026-10-07)

Tracker #272; ADR-005; commit ceb73cf. All 11 tickets are built and labelled `status: ready-for-qa`, with evidence on each.

## Built
| Ticket | Where |
|---|---|
| SYS-93 escape | `web/answer.py` (segments), `_answer.html` (no `| safe`), `query_processor.safe_link` |
| SYS-92 topic filter | `web/filters.py` (`TOPIC_CHOICES` = rubric topics minus soft), `QueryProcessor._fts_search` (filters in SQL), `_attach_metadata` (DB truth; a hit without an article is dropped), `_apply_filters` |
| SYS-94 states | `QueryProcessor.answer` → `AnswerResult(ok/unavailable/failed/no_hits)`; `/api/answer/{turn_id}`; copy in `web_copy` |
| SYS-95 names/dates | `card()` (`outlet()`, `tanggal_kartu`), prompt header (`answer.header`); no timing or "chunks" anywhere |
| SYS-96 a11y | labels on every control, named buttons, tokens tested >= 4.5:1 (text) and >= 3:1 (borders, focus) in both themes; `--control-line` added for input borders |
| SYS-97 thread | `_turn.html` OOB follow-up form with the session (`hx-swap="beforeend"`); the search form has no session id; "Pertanyaan baru" in `static/page.js`; only an `ok` answer enters history, with `[n]` stripped |
| SYS-98 provider | `Summarizer.complete()` + `Reply`; `RAG_LLM_PROVIDER` (default `openai`); usage under `web:<model>` with tokens and `peak_hours.cost_usd`; `RAG_DAILY_COST_LIMIT_USD` |
| SYS-99 prompt | `answer.PROMPT` (the PM's text verbatim), `clean`, `parse`, `cited`, `unverified_number`; no model call without hits |
| SYS-100 filters | portal dropdown from `site_stats` (brand names), date chips (7/30/custom with labelled Dari/Sampai), topic dropdown, removable chips (OOB), "Hapus filter" |
| SYS-101 copy | `core/web_copy.py`; a test proves the templates hold no literal reader text |
| SYS-102 visual | `style.css` from the approved mockup, `_turn.html` / `_answer.html`, two-step loading, warm-up lifespan, htmx vendored |

## Deviations from the plan / the PM text
- **Disclosure** reads "artikel sumber", not "di bawah" (owner-approved with the mockup). The FAILED copy names "daftar sumber" for the same reason: on desktop the sources sit beside the answer.
- **The hero** has a heading the PM text did not have ("Tanyakan apa saja tentang berita Indonesia hari ini.", in the approved mockup). "Diperbarui {kapan}" shows the day when the last article crawl was not today.
- **Topic is a dropdown**, not chips (the ticket allows either; 12 options fit a select better on a phone).
- **Active-filter chips** are rendered by the server for the question just asked, out-of-band. Removing one resets the control for the next question; it does not re-ask.
- **The JSON API:**
  - it lost the `category` field (now `topic`) and its HX-fragment branch (unused by the page);
  - it returns 422 for an empty or too-long question;
  - it no longer reports `query_ms` (that is in the log).
- **Input borders** use a darker token than the mockup's hairline (WCAG 1.4.11 needs 3:1).
- **Found and fixed during the build:**
  - the app's INFO lines were dropped under uvicorn (`logger.setLevel`);
  - the search indicator always showed (a CSS specificity clash).

## Evidence
- **Tests:** unit 2,609 passed, 5 skipped; integration 193 passed, 1 skipped (outbox isolated per OPS-46).
  - New files: `test_rag_answer.py` (35), `test_rag_answer_states.py` (16), `test_rag_filters.py` (26), `test_rag_page.py` (41), `test_rag_contrast.py` (41), `test_rag_turns_and_stats.py` (7), `test_summarizer.py` (+8), `integration/test_rag_filters_live.py` (6).
- **Mutants:** 42 registered in `qa_mutation_runner.py` (`sys92_*` … `sys102_*`), 42/42 killed in a scratch worktree.
- **Live (production read-only, plus usage rows):**
  - 10-question replay on DeepSeek: 10/10 answered, all checks clean, $0.0003-0.0004 per answer;
  - 1 question on Gemini;
  - warm-up 14.8 s; first question after start-up: retrieval 62 ms.
  - The details are in EXPERIMENTS.md, 2026-10-07.
- **Screenshots:** 375/1280 px, light/dark, hero and answered, via `snapshot_rag_page.py`.

## Tech debt / follow-ups
- **SYS-103 (#273):** FTS ANDs every word (`fts=0-1` per question). Filed, not fixed (outside the critique's tickets).
- **Keyboard pass:** done by `scripts/experiments/e2e_rag_page.py` (headless Chrome over CDP, keys only, 14/14). Neither axe nor a screen reader was used; contrast and labels are covered by unit tests.
- **Before sharing the page:** auth, a rate limit, self-hosted fonts (security review).
- **The owner's own uvicorn on :8000** still runs the old code until restarted.
