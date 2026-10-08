# Chunks fit the encoder window (SYS-109 #283): what was built (SDE, 2026-10-08 evening)

ADR-008. Commits 377fbbd (design), b25dd36, 3aea301, 6ddae23 (+ docs).

## Built
| What | Where |
|---|---|
| Chunk defaults 40 / 80 / 20 (min / max / overlap) | `core/constants.py` |
| L2-only re-chunk: `--all`, `--resume`, one backup per run (NEWS_L2 + `l2_rows.jsonl`), `--group` 50 articles per embedding batch, `--block` 5,000 per flush, one shared repository, `ANALYZE chunks` | `scripts/rechunk_stale_chunks.py` |
| `group_size` for the shared re-chunk (default 1 = unchanged; a failed group retried one by one) | `scripts/backfill_orphan_chunks.rechunk_articles`, `repair_boilerplate_bodies.rechunk` |
| DBT-64 #286: indexes on `entity_mentions(chunk_id)`, `(sitemap_id)` | `scripts/migrate_entity_mentions_indexes.sql`, `scripts/migrate.py` |
| Probe | `scripts/experiments/probe_encoder_window.py` |

## Deviations from the design
- **Chunk window:** the design assumed 128 tokens hold ~97 words; measured, it is ~83. That moved the choice to 80-word windows (best late recall of 70/80/90) rather than ~90.
- **Mentions:** the SYS-105 detach/re-attach is gone. L2-only never touches them; re-attach stays only as an idempotent clean-up for a run of the old version.

## Evidence
- unit 2,765 passed / 5 skipped; integration 207 passed / 1 skipped (the DBT-64 migration applied to `newsaggregator_test`, both indexes present).
- New: `test_chunker_helpers.TestChunksFitTheEncoderWindow` (4); `test_store_repair_targets` (+6, incl. grouped re-chunk); `tests/integration/test_rechunk_stale_chunks_live.py` (5: fragments, `--all` windows, resume, dry run, crawl refusal).
  - The live tests assert the L1 row, L1 vector and mention are identical before and after.
- Mutants `sys109_*`: 7/7 killed (distinct counts, fresh worktree).
- Dry run on production: 100,466 articles, L2 358,162 → 713,589, > 80 words 298,576 → 0.

## Tech debt / follow-ups
- NEWS_L2 roughly doubles (~3.5 GB per loading process); SYS-41 owns capacity (HNSW / sharding).
- The crawl embeds ~40% more tokens per article (overlap).
