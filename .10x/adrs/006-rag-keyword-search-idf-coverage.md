# ADR-006: The search page's keyword half matches the question's rare words and ranks by IDF-weighted coverage, in Postgres

**Status:** Accepted 2026-10-07 (owner: "lets do that", after weighing Elasticsearch)
**Date:** 2026-10-07
**Feature:** rag-keyword-search (SYS-103 #273)
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
`QueryProcessor._fts_search` matches `plainto_tsquery('simple', question)`. That ANDs every word of the question, function words included, so a paragraph has to contain all of them. In the 2026-10-07 replay it found 0-1 paragraphs per question, and the ranking was semantic + recency only. The exact names that a keyword search exists for ("BI-Rate", "IHSG", "KPK") could not lift an article: the BI decision ranked below two forecast pieces.

Measured on production, read-only (`probe_fts_query_shapes.py`, 359,530 L2 paragraphs, 9 replay questions; EXPERIMENTS.md 2026-10-07):

| Shape | Matches to rank | Latency | On topic |
|---|---|---|---|
| every word ANDed (today) | 0-5 | — | nothing found |
| every content word ORed | 7,803-95,851 | 358-6,922 ms | noisy |
| rare words ORed (df < 2%) | 102-11,124 | 16-202 ms | 7/9 |
| IDF-weighted coverage | 221-11,124 | 46-265 ms | 9/9 |

How often a word occurs (its document frequency, df) is what separates "BI-Rate" (0.09% of paragraphs) from "indonesia" (22%). Counting it exactly costs up to ~800 ms for a question with common words. Postgres already keeps the answer for the common ones: `pg_stats.most_common_elems` on `chunks.fts_vector` lists the 1,000 most frequent words with their share. That share is sampled by ANALYZE over L1 and L2, and lies within 0.4 points of the exact L2 count for every word checked. Reading it takes 30 ms. Every word missing from that list is below its smallest share (1.47%), which makes it rare and cheap to count exactly.

Elasticsearch was considered and set aside for now (owner, 2026-10-07): it would bring BM25 and Indonesian stemming, but as a new JVM service with a sync pipeline. Speed is not the problem: retrieval takes 62-125 ms, and the 1.4-5 s answer is the model's time.

## Decision
1. **Terms:** the question's content words. Split them from the question, then drop:
   - `story_words.STOPWORDS`;
   - question words ("apa", "bagaimana", "terbaru", …);
   - one-letter tokens and duplicates.

   Keep the first 12. A word is a *name* when it is upper case or has a digit, or when it is capitalised and is not the first word.
2. **Document frequency:** `web/keywords.DocFrequency` gives each word its share of L2 paragraphs, cached per process for 24 h:
   - a common word: from `pg_stats.most_common_elems`;
   - any other word: an exact count (capped);
   - the L2 total: `COUNT(*)`.

   With no planner statistics (a fresh or test database), every word is counted. A word that occurs nowhere (a typo) is dropped. A question with no word left does no keyword search.
3. **Which paragraphs:** the anchors are the words under 3% df, plus the names under 10%; when there are none, the rarest word. A paragraph must contain at least min(2, number of anchors) anchors, and at least one name when an anchor is a name.
4. **Score:** coverage = the sum of idf(w) = ln(1/df) over the words present, divided by the sum over all of them. It lies in [0, 1].
   - Paragraphs are ordered by coverage, then by `ts_rank_cd` on the anchors. Measured: newest-first as the tie-break pulled droughts into the flood question and a Wall Street piece into the Iran question; recency stays the re-rank's job.
   - It replaces `ts_rank` as the hit's keyword score (`keyword_score`, formerly `bm25_score`). The re-rank uses it as is, with no ×10.
5. **Floor:** a hit is kept when its semantic score is >= `RAG_MIN_SEMANTIC_SCORE` or its coverage is >= `RAG_MIN_KEYWORD_COVERAGE` (new, default 0.6). It used to be "any keyword match".
6. **SQL safety:** every word is a bind parameter, and so is every weight. The SQL text is built only from fixed fragments and parameter names.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Elasticsearch (BM25, Indonesian analyzer) | Real BM25, stemming, filtered kNN | New JVM service, Postgres→ES sync, FAISS writers and run-lock tests to port; 1-2 weeks | Owner set aside 2026-10-07; revisit if the replay still misses on word forms |
| OR of every content word, `ts_rank_cd` | One line | 7,803-95,851 matches, up to 6.9 s; noisy ranking | Measured too slow and too noisy |
| OR of rare words only | Fast | 7/9: "Iran" → agrarian conflicts, "minyak" → cooking-oil promos | Loses the common-but-decisive word |
| Exact df counts per question | Simple | ~800 ms cold for common words | Misses the < 400 ms target; `pg_stats` gives the same answer in 30 ms |
| A df table kept by the crawler | Exact, instant | Migration + a write path in the crawl + backfill | Production schema change for a P3; the stats are close enough |
| ParadeDB / pg_search BM25 | BM25 in Postgres | Needs PG 14+; production is 12.2 | Not installable |

## Consequences
### Positive
- The keyword half contributes again, and an exact name lifts the article that carries it.
- No new service, no schema change, no production write.
- The per-word work is cached: a repeated word costs nothing for 24 h.

### Negative
- Still no stemming: "melemah" does not match "pelemahan".
- The df of common words is ANALYZE's sample over L1 + L2, not the exact L2 share (within 0.4 points where checked).
- One more knob: `RAG_MIN_KEYWORD_COVERAGE`.

### Risks
- **Stale statistics:** autovacuum re-analyzes `chunks` as it grows; the 24 h cache adds at most a day. Mitigation: df only weights words and picks anchors, so a few points of drift cannot exclude an article.
- **A rare unrelated word in a long question** may become an anchor that never co-occurs. Mitigation: at most 2 anchors are required, typos (df 0) are dropped, and the semantic half still answers.
- **A coverage floor of 0.6 is a judgment.** The replay reports the coverage of the kept hits; QA can tune it by env.

## Dependencies
- `chunks.fts_vector` (`to_tsvector('simple', …)`, GIN index) and planner statistics on it.
- `story_words.STOPWORDS`.
- ADR-005's hybrid retrieval and re-rank.
- Constrains: a later move to Elasticsearch or pgvector replaces `web/keywords.py` and `_fts_search` only.
