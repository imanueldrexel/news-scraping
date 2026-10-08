# ADR-008: L2 chunks are ≤ 80-word windows that fit MiniLM's 128-token input; the encoder stays

**Status:** Accepted 2026-10-08 (owner: "design it and fix it directly after the design is finished")
**Date:** 2026-10-08
**Feature:** chunks-fit-encoder-window (SYS-109 #283; DBT-64)
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
- **The mismatch:**
  - MiniLM embeds the first 128 tokens of a text, a median of ~83 Indonesian words. The rest is not in the vector.
  - L2 chunks were 80-450 words (`CHUNK_MAX_TOKENS` 450, overlap 50).
  - So for a long paragraph, semantic search saw its first fifth to half.
- **What it cost:**
  - On 300 long production paragraphs among 4,000, a sentence from after word 130 found its paragraph at rank 1 in **13.7%** of cases; one from the first 60 words in 73%.
  - ADR-007 had to lean on the keyword half for names mentioned late ("Danantara": cosine 0.18-0.29 on paragraphs about it).
- **Scope:**
  - NEWS_L1 vectors are written but never searched.
  - The newsletter clusters L1 leads, where the opening is the point.
  - The scope is NEWS_L2, the search index.

## Decision
1. **L2 chunks of ≤ 80 words with 20-word overlap; short paragraphs merge from 40 words:**
   - `CHUNK_MAX_TOKENS` 80, `CHUNK_OVERLAP_TOKENS` 20, `CHUNK_MIN_TOKENS` 40.
   - Each chunk is one vector and one row, as before. The one-vector-per-row invariants of SYS-17/53/54/56/61 and the store checks are kept.
2. **The encoder is unchanged** (MiniLM, 128 tokens, its SYS-61 revision record). L1 is unchanged.
3. **The stored corpus is re-chunked L2-only** by `scripts/rechunk_stale_chunks.py --all`:
   - L1 rows, L1 vectors and entity mentions (which point at L1) are untouched;
   - one backup per run; resumable;
   - `ANALYZE chunks` at the end.
4. **DBT-64:** `entity_mentions(chunk_id)` and `entity_mentions(sitemap_id)` get indexes. Without them every chunk delete scans the mentions table: deleting 17,222 rows took 9 minutes.

## Alternatives Considered
| Alternative | Measured (late / early recall@1) | Why not |
|---|---|---|
| Raise MiniLM's `max_seq_length` to 256 / 512 (its position table has 512) | 0.187 / 0.320; 0.013 / 0.020 | Trained at 128: longer inputs destroy even what it saw before |
| multilingual-e5-base (512 tokens) | 0.407 / 0.713 | Worse than windows and 6x slower: 13 h to rebuild, and every crawl and query pays it. A new index pair, a new revision record, and the newsletter's clustering to retune |
| ≤ 70-word windows (fit 95% of windows) | 0.723 / 0.763 | 9% more vectors than 80 for lower late recall |
| ≤ 90-word windows | 0.690 / 0.747 | 82% of windows still truncate |
| Several vectors per stored paragraph (keep the text units) | same as windows | Breaks one-vector-per-row: chunks.embedding_id, the SYS-17 reuse key, SYS-54 discards, store checks and repair tools all assume it |
| Leave it (ADR-007's keyword half carries late names) | 0.137 / 0.730 | Only exact words are found; meaning late in a paragraph is lost |

## Consequences
### Positive
- Late content is found 5.5x more often (13.7% → 75.0% at rank 1); early content is unchanged (73.0% → 75.3%).
- No new model or service. The crawl, the queries and SYS-61's record are unchanged.
- Answer excerpts are unchanged in size (`MATCH_CHARS` 700 ≈ one window).

### Negative
- L2 grows ~2.15x: 373k → ~800k rows and vectors.
  - NEWS_L2 ~1.8 → ~3.5 GB on disk and in every process that loads it.
  - A flat search goes from ~40 to ~90 ms.
  - SYS-41 (capacity) is the follow-up.
- The overlap adds ~40% embedding work per article in the crawl.
- The keyword half matches within 80-word windows. An anchor pair split across a window boundary is found only within the 20-word overlap. `pg_stats` df shares shift (ANALYZE at the end).

### Risks
- **FTS recall on long paragraphs drops.** Mitigation: the replay is re-measured; rollback is restoring NEWS_L2 and the L2 rows from the run's backup.
- **A 6-8 h production rebuild.** Mitigation: run lock, `--until`, `--resume`, blocks of 2,000; L1, mentions and articles untouched.

## Dependencies
- SYS-17 reuse path (an existing L1 vector is found by its key and not re-inserted).
- ADR-007 retrieval, unchanged.
- SYS-41 owns the capacity follow-up.
