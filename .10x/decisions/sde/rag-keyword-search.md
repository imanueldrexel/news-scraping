# RAG keyword search (SYS-103 #273): what was built (SDE, 2026-10-07)

ADR-006; commit c69d34d. Labelled `status: ready-for-qa`, with evidence on the ticket.

## Built
| Unit | Where |
|---|---|
| Content words, names, at most 12 | `web/keywords.terms` |
| df per word: `pg_stats` for common words, an exact count (LIMIT 10%) for the rest, 24 h cache under a lock | `web/keywords.DocFrequency` |
| Anchors / names / need / normalised idf weights; typos (df 0) dropped | `web/keywords.KeywordQuery.build` |
| SQL from fixed fragments, words and weights as bind parameters, filters as before | `QueryProcessor._fts_sql` / `_fts_search` |
| `keyword_score` (was `bm25_score`) in the merge and the re-rank (no ×10); the floor at `RAG_MIN_KEYWORD_COVERAGE` | `QueryProcessor.retrieve` / `_merge` / `_re_rank`, `core/constants.py` |
| Log: `kept_by_keyword=` | `retrieve` |

## Deviations from ADR-006
None in behaviour. Measured on top of the ADR:
- the cold-page latency (below);
- a check that the df cap barely matters (the count's cost is in the words between 2% and 10%), which is why `pg_stats` is used.

## Evidence
- **Tests:**
  - unit 2,655 passed / 5 skipped; integration 198 passed / 1 skipped;
  - new: `test_rag_keywords.py` 42, `test_query_processor_ranking.py` +4, `integration/test_rag_keywords_live.py` 5;
  - `test_rag_filters.py`: two SQL-shape tests adapted, with `keyword_df` stubbed.
- **Mutants:** 25 `sys103_*`, 25/25 killed.
- **Replay** (11 questions):
  - `fts=20` on 11/11; kept by keyword on 10/11;
  - the BI-Rate decision at ranks 3-5;
  - 11/11 answers ok.
- **Latency:** keyword half 15-313 ms (df 0-140 ms on first sight); retrieval 108-358 ms warm, up to 1.3 s on cold Postgres pages (was 62-125 ms with an empty FTS).

## Tech debt / follow-ups
- **No stemming or phrase match:** "suku bunga terbaru" still gives forecasts. That's the next lever if the owner wants it, possibly Elasticsearch's analyzer or a Postgres Indonesian dictionary.
- **Opinion pieces holding every word** can outrank news (BI-Rate ranks 1-2). A topic-agnostic fix is not obvious; leave it for QA's or the owner's hand check.
- **`RAG_MIN_KEYWORD_COVERAGE=0.6` is a judgment.** The replay's sources were mostly coverage 1.0.
- **Fixed on the way:** a bare CR in EXPERIMENTS.md (d2b48d4) failed `test_repo_hygiene`.
