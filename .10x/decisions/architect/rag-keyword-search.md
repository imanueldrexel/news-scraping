# RAG keyword search (SYS-103 #273): design (Architect + Staff Engineer, 2026-10-07)

ADR-006. The owner chose this over Elasticsearch on 2026-10-07: the problem is relevance, not speed.

## Components
| Unit | Does | Depends on |
|---|---|---|
| `web/keywords.py` `terms(question)` | the content words of the question, with a name flag; at most 12 | `story_words.STOPWORDS` |
| `web/keywords.py` `KeywordQuery.build(terms, df)` | drops df-0 words; picks the anchors, the names, how many anchors are needed, the normalised idf weights; None when no word is left | pure |
| `web/keywords.py` `DocFrequency(client)` | df per word (`pg_stats` for common words, an exact capped count for the rest); 24 h cache under a lock | the DB session |
| `QueryProcessor._fts_search` | builds the SQL from a `KeywordQuery` (fixed fragments, bind parameters) plus the existing filter fragments | the two above |
| `QueryProcessor.retrieve` / `_re_rank` | floor: `keyword_score >= RAG_MIN_KEYWORD_COVERAGE`; re-rank uses the coverage as is | constants |

## Data flow
question → `terms` → `DocFrequency.get(words)` → `KeywordQuery.build` → SQL (anchor OR via the GIN index, the anchor count, the name rule, filters) → paragraphs with `keyword_score` = coverage → `_merge` (max per article) → metadata → filters → re-rank → floor.

## Failure modes
- **The df lookup or the FTS query fails:** `_fts_search` logs a warning and returns `[]`, as today. The semantic half answers alone.
- **`pg_stats` has no row** (never analyzed, or no permission): every word is counted exactly. It is slower but correct.
- **No word left** (a question of only stop words): no keyword query, no SQL.
- **Concurrency:** FastAPI runs sync handlers in a thread pool, so the cache is guarded by a lock. The DB work runs outside the lock, so two threads may count the same word once each, which is harmless.

## Staff-engineer notes
- **Naming:** the hit's `bm25_score` becomes `keyword_score`, because it was never BM25 and is now a coverage. The env variable `RAG_BM25_WEIGHT` keeps its name (operators' `.env`) and gets a comment.
- **Tests:**
  - pure tests for `terms` and `KeywordQuery.build`;
  - `DocFrequency` against a fake session: stats used for common words, counts for the rest, the cache, the fallback without stats;
  - the SQL shape: words only as bind parameters;
  - the floor and the re-rank.
  - Live in `newsaggregator_test`, an integration test: a name finds its article, and a question of stop words finds nothing.
- **Mutants:** `sys103_*` in `qa_mutation_runner.py`.
- **Evidence:** `replay_rag_answers.py` with the `fts=` counts from the log; the BI decision in the top 5; EXPERIMENTS.md before and after.
