# Chunks fit the encoder window (SYS-109) -- senior engineer

- **L2-only delete:**
  - `sys73.delete_vectors(targets, [L2 dir])` deletes the targets' L2 vectors only. Check: `vector_ids_for` picks by sitemap_id, so passing only the L2 dir keeps L1 vectors.
  - Then `DELETE FROM chunks WHERE sitemap_id = ANY(:ids) AND chunk_level = 2`.
- **Re-chunk:** `sys73.rechunk()` selects articles missing L1 *or* L2 (`backfill_orphan_chunks._FETCH_SQL`). `save_chunk_data` then embeds the new L2 and finds L1 by its key (SYS-17), not re-inserted. Verify that in the integration test: the L1 chunk_id and its vector id are unchanged.
- **`--all` targets:** every article whose stored L2 word counts differ from the chunker's. Fetch per source (ids + text + layout), never `GROUP BY` the text (Docker /dev/shm trap).
- **Backup per run:** copy NEWS_L2 only (L1 untouched), plus JSON of the L2 rows to delete. `--resume` skips the target computation's backup and deletion and only runs `rechunk` for the articles missing L2 (orphans), then ANALYZE.
- **Block size** 2,000 (fewer whole-index flushes of a ~3.5 GB pair).
- **Mention re-attach:** the SYS-105 detach/re-attach goes (L2-only never touches mentions), but keep the re-attach SQL in `--resume` for a run interrupted by the old version (idempotent).
