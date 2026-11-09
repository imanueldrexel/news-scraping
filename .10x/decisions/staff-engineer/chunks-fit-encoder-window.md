# Chunks fit the encoder window (SYS-109) -- staff engineer

- **Reuse:** the existing repair machinery
  - `repair_boilerplate_bodies.backup` / `delete_vectors` (restricted to the L2 dir) / `rechunk` / `parse_until` / `_crawl_running`;
  - `backfill_orphan_chunks.rechunk_articles`;
  - the SYS-17 reuse path for L1.
  - No new FAISS code.
- **Measure before shipping:** `probe_encoder_window.py` (new, reusable) chose the window, and `probe_rag_rank_breakdown.py` is the before/after gate on the replay.
- **Standards:**
  - the migration follows OPS-05 (registered in `scripts/migrate.py`, applied to both DBs, DBT-22: quote `tests/integration`);
  - CRLF-stored docs are edited per line (`git diff` == `git diff -w`);
  - mutants for the new boundaries.
- **Docs to update:** CLAUDE.md (the chunker line, the migration list), OPERATIONS.md (env defaults, the rebuild runbook), EXPERIMENTS.md (the measurement and the run).
