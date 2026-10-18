# Architect — QA's 2026-10-13 queue (worked 2026-10-19)

Tickets: SYS-144 #327 (send-back), SYS-145 #328 (send-back), SYS-146 #331, DBT-60 #258 (send-back), DBT-70 #332,
DBT-71 #334, SRC-62 #333; filed while measuring: SYS-194 #396 (fixed here), SYS-195 #397 (not here).

## Follow-up resolution and keyword terms (ADR-021)
- **Component:** new `newscrawler/web/nya_words.py`, pure. It is the one definition of a word ending in -nya: `ADVERBS`
  (no referent), `NOT_CLITIC` (hanya, punya, tanya, bertanya), `is_reference(word)`, `possessive_root(word)`.
- `followup.refers_back(question)` stays lexical: reference word present, adverbs excluded. QA's tests call it with
  one argument.
- New `followup.refers_to_thread(question, previous)`: refers_back AND no own subject (ADR-021 decision 1).
  `resolve` uses it on the `kept` path and the fallback. The `alone` / `llm` paths are untouched.
- `keywords.terms`: a possessive -nya word is replaced by its root, and an adverb is skipped (ADR-021 decision 3).
- Data flow is unchanged: `QueryProcessor.resolve` → `followup.resolve` → `Retrieval` → `_keyword_query(*questions)`
  → `terms`.
- **Failure modes:** none new. All of it is pure string work; a wrong judgement degrades to retrieving the follow-up
  on its own words (no error path).

## SYS-194: deterministic keyword half
- `_fts_sql` ORDER BY gets a unique last key, `c.chunk_id DESC`. Among exact ties the newer paragraph comes first,
  in line with the page's recency preference. ADR-006's measured tiebreaks (coverage, then ts_rank_cd) are unchanged
  above it.

## DBT-60: the date rule, numerically
- `posted_at_datetime`: any `numbers.Real` that is not a bool (Decimal and numpy scalars included), and any string
  that parses as a number (sign, decimal point), is a yyyymmdd when integral and 8 digits, and is refused otherwise.
  Only a non-numeric string goes to pydantic. Unix seconds are never accepted in any form.

## DBT-70: "terminal" lives in the toolkit
- `_load_state` moves to `newscrawler/tools/store_repair.py` as `sitemap_state(session, sitemap_ids)` (OPS-25's one
  definition). repair_store_consistency and check_store_consistency import it from there. The scheduled crawl's
  store check no longer reaches into a repair script.

## SRC-62: INVESTORID section
- `_get_branch_name_from_url` matches the section and returns it, or None (`usable_section_name` → branch fallback).
- `money-lab` is a soft guides vertical (sample on the ticket). It goes in `SOURCE_SOFT_LEAVES["INVESTORID"]`, so the
  category gate settles it before fetch (SYS-50). The crawler's `SOFT_BRANCH_DENY` points at the same set (SRC-50
  pattern).
