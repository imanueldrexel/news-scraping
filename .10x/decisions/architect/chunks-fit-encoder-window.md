# Chunks fit the encoder window (SYS-109 #283) -- architect

ADR-008. Spec: `.10x/specs/2026-10-08-sys109-chunks-fit-encoder-window-design.md`.

## Components touched
- `core/chunker.py` (via `core/constants.py`): L2 = windows of at most 80 words, 20-word overlap, min 40. L1 is unchanged.
- `scripts/rechunk_stale_chunks.py`: the store repair becomes **L2-only**. L1 rows, L1 vectors and mentions are kept; the SYS-17 reuse path re-finds the L1 vector. Modes `--min-words` (SYS-105) and `--all` (SYS-109); one backup per run; `--resume`; `ANALYZE chunks` at the end.
- `scripts/migrate_entity_mentions_indexes.sql` (DBT-64): indexes on `entity_mentions(chunk_id)` and `(sitemap_id)`.
- **Not touched:** the encoder, `ChunkFAISSDatasource`, retrieval (ADR-007), the newsletter, extraction.

## Boundaries and invariants kept
- One vector per chunk row (`chunks.embedding_id`), so store checks, SYS-54 discards and repair tools hold.
- One encoder per index pair (SYS-61): the encoder does not change.
- Run lock and the generation-checked atomic save for every FAISS write (OPS-26, SYS-53/56).

## Failure modes
| Failure | Effect | Handling |
|---|---|---|
| Killed mid-run | Some articles' L2 rows and vectors deleted, not yet re-chunked | `--resume`: `rechunk()` picks up articles missing L2; the backup is kept |
| A crawl due (07:00/19:00) | The lock is held: the crawl refuses for that run | `--until 06:15`; run only in free windows |
| FTS recall worse on windows | Keyword-only finds drop | Re-measure the replay; rollback from the run's backup |
| RAM | ~3.5 GB per process that loads NEWS_L2 | 33.7 GB machine; SYS-41 follow-up |
