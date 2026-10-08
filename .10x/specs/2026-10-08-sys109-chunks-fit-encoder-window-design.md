# SYS-109: L2 chunks fit the encoder's window (design, 2026-10-08)

**Ticket:** SYS-109 #283 (P2). **ADR:** ADR-008. **Owner instruction (2026-10-08):** "design it and fix it directly after the design is finished".
**Feature slug:** `chunks-fit-encoder-window`.

## Problem
- MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`) embeds only the first 128 tokens of a text.
- L2 chunks run to 450 words.
- On real paragraphs 128 tokens hold a median of **~83 words**, not ~97 as SYS-109 first said: Indonesian runs ~1.53 tokens per word (90-word windows: p50 138 tokens).
- So most of a long paragraph is invisible to semantic search.
- NEWS_L1 is not searched. The newsletter clusters on the lead, where the first ~83 words are the point. **L2 (search) is the scope.**

## Measurement (`scripts/experiments/probe_encoder_window.py`, production read-only)
- **Setup:** 300 paragraphs of ≥ 200 words among 4,000 random L2 paragraphs.
  - Query = a sentence from late in the paragraph (after word 130), or from early in it (first 60 words).
  - Measured: the source's recall@1.

| Option | late r@1 | early r@1 | corpus re-embed |
|---|---|---|---|
| today (MiniLM, 128 tokens, whole paragraph) | 0.137 | 0.730 | — |
| MiniLM, `max_seq_length` 256 | 0.187 | 0.320 | 3.4 h |
| MiniLM, `max_seq_length` 512 | 0.013 | 0.020 | 4.3 h |
| ≤ 70-word windows (overlap 20), best window | 0.723 | 0.763 | 5.7 h |
| **≤ 80-word windows (overlap 20), best window** | **0.750** | **0.753** | **5.0 h** |
| ≤ 90-word windows | 0.690 | 0.747 | 4.3 h |
| multilingual-e5-base, 512 tokens | 0.407 | 0.713 | 13 h (8 paragraphs/s) |

MiniLM was trained at 128 tokens, and a longer window destroys its vectors. e5-base is worse and 6x slower, for every crawl and every query too.

## Design
1. **Chunker:** `CHUNK_MAX_TOKENS` 450 → **80**, `CHUNK_OVERLAP_TOKENS` 50 → **20**, `CHUNK_MIN_TOKENS` 80 → **40** (min must not exceed max).
   - Short paragraphs still merge forward, and the last one backward (SYS-105).
   - A long paragraph is split into ≤ 80-word windows that overlap by 20.
   - L1 is unchanged (the first two paragraphs). The encoder is unchanged, so SYS-61's revision record stays valid.
2. **Repair (`scripts/rechunk_stale_chunks.py`) becomes L2-only:**
   - It deletes the targets' **L2** vectors and **L2** rows, and re-chunks.
   - The L1 rows and vectors are kept and found again by `save_chunk_data`'s reuse path (SYS-17).
   - The entity mentions, which point at L1 chunks, are untouched: no detach, no re-attach, nothing re-extracted.
   - Targets are the articles whose stored L2 layout differs from the chunker's:
     - `--min-words N`: those holding an L2 chunk under N words (SYS-105);
     - `--all`: every article (SYS-109).
   - **One backup per run:** NEWS_L2 plus the deleted L2 rows as JSON. `--resume` continues a stopped run without a new backup.
   - Blocks of `--block` articles (default 2,000) per FAISS flush; `--until HH:MM`.
   - `ANALYZE chunks` at the end, so the keyword half's `pg_stats` df reflects the new rows.
3. **DBT-64 (new): indexes on `entity_mentions(chunk_id)` and `entity_mentions(sitemap_id)`.**
   - Deleting a chunk row checks the FK by a sequential scan of 230,061 mentions: deleting 17,222 rows took 9 minutes today.
   - Migration `scripts/migrate_entity_mentions_indexes.sql`, registered in `scripts/migrate.py`. Applied to `newsaggregator_test` by the suite, to `newsaggregator` before the rebuild.
4. **Unchanged:**
   - the retrieval code (ADR-007), its `MIN_PARAGRAPH_WORDS` 15 and its thresholds;
   - the answer excerpt (`MATCH_CHARS` 700 ≈ 100 words is already about one window);
   - the newsletter (L1), extraction (article text), FTS (on L2 rows, now windows).

## Production run
- **Order:**
  1. a fresh `backup_db.py` dump;
  2. the migration;
  3. `rechunk_stale_chunks.py --all --apply --until 06:15` after the 19:00 crawl releases the lock;
  4. `--resume` in the next window if it stops.
- **The 21:00 extraction** waits for the run lock (up to 90 min) and then skips the night. The SumoPod key is blocked anyway.
- **Expected:** L2 373k → ~800k rows/vectors; NEWS_L2 ~1.8 GB → ~3.5 GB on disk and per loading process (RAM 33.7 GB); a flat search ~2x slower (40 → ~90 ms).

## Verification
- **Unit:** chunker windows ≤ 80 words with 20 overlap; the trailing merge still holds. The repair is L2-only (L1 rows, L1 vectors and mentions unchanged), with `--all` targets and `--resume` skipping the backup.
- **Integration:** a long article's L2 rows become windows with vectors, its L1 and mention are untouched, a second run finds nothing; the migration applies to the test DB.
- **Live after the rebuild:**
  - L2 chunks over 80 words = 0 (excluding whole-article-only cases);
  - `check_store_consistency.py` all zero;
  - `probe_rag_rank_breakdown.py --replay --followups` against today's final numbers (keyword-only 50/160; BI-Rate, Danantara, gold, follow-ups);
  - retrieval latency on a second uvicorn.

## Rollback
1. Restore the NEWS_L2 backup directory over `NEWS_L2`.
2. Re-insert the L2 rows from the run's JSON, after deleting the new L2 rows.
3. Revert the chunk constants.

L1, the mentions and the articles are never touched.
