# Chunks fit the encoder window (SYS-109 #283): what was built (SDE, 2026-10-08 evening)

ADR-008. Commits 377fbbd (design), b25dd36, 3aea301, 6ddae23 (+ docs); SYS-111 5fcb58a, 8832fc4; production evidence d039874.

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

## Production run (2026-10-08 20:04 → 2026-10-09 00:30)
- `backup_db` (`newsaggregator_20261008T130309Z.dump`) → `migrate.py` (DBT-64) → `--all --apply --until 06:15`.
- **SYS-111 #287 (found, fixed):** `--until 06:15` at 20:04 meant today's 06:15. The run deleted 358,398 L2 rows and vectors (backup `backups/sys109_ALL_20261008T130410Z`) and stopped with exit 3.
  - Mitigation: `--apply --resume` with no deadline, started 20:05.
  - Fix: `parse_until` is the next HH:MM; both write paths exit 2 before backup/deletes when the deadline is < 15 min away.
  - Evidence: 5 mutants killed; integration test of the incident shape.
- Resume: 100,466 articles, 0 empty, 0 failed, ~7/s, `ANALYZE chunks`.
- **After:**
  - 737,682 L2 rows on articles, 0 over 80 words; NEWS_L2 750,871 vectors;
  - store consistency all zero; dry run TOTAL 0.
  - Late recall@1 0.020 → 0.360 (@20 0.145 → 0.725); early @1 0.620 → 0.580.
  - Warm retrieval median 0.3 s; web process 7.6 GB.
- **SYS-112 #289 (found, filed, not fixed):** "Menkeu sekarang" / BI-decision regress in the replay probe; same-day keyword hits now clear the 0.55 recency gate. Needs a re-tune on the windowed scores.
- **OPS-47 #288 (my incident, fixed):** `git worktree remove --force` on the SYS-111 mutation worktree recursed into its `venv` junction and deleted 23 packages of the real venv.
  - Repaired from the pins: `pip freeze` == `requirements.txt`, unit suite green.
  - The runner's docstring now gives the safe teardown.

## Status
SYS-109 #283, DBT-64 #286, SYS-111 #287, OPS-47 #288: ready-for-qa. SYS-112 #289 open.
