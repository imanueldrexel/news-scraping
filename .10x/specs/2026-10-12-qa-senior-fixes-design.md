# Design: the QA (2026-10-12) and senior-engineer (2026-10-12) ticket list

**Date:** 2026-10-12
**Role:** dev (CLAUDE.md "dev does the ticket, QA closes it"): every ticket ends `status: ready-for-qa` with evidence, never closed by dev.
**Inputs:** `.10x/reviews/2026-10-12-qa-report.md`, `.10x/reviews/2026-10-12-senior-code-quality-audit.md`, the tickets' QA comments.
**Owner decisions (2026-10-12, asked as CTO/PM):**

| Question | Owner's answer |
|---|---|
| SYS-139: how the worker protects its vectors | **Soft deadline only** (no periodic flush) |
| SYS-104 + SYS-140: how a follow-up uses the thread | **An LLM rewrites the follow-up into a standalone question** (supersedes ADR-007 decision 4) |
| SYS-137: the queued VIVA rows with 450-word chunks | **Delete their chunk rows + vectors; the crawl chunks them fresh.** Production write, backup first, between crawls |
| SYS-138 + SYS-112: recency re-tune | **Soft date window** for "pekan/minggu ini"; "sekarang/hari ini" freshness only for an article about the question |

## Scope and order

1. **SYS-111 #287 (P1, sent back).** `repair_boilerplate_bodies._apply_locked` resolves `--until` once; that value goes to `too_close` and `rechunk`. Test: QA's fake clock moves past the deadline between the guard and the re-chunk. Mutant: resolve it again.
2. **SYS-139 #320 (P2).** Soft deadline in the source worker: ADR-011.
3. **SYS-104 #274 + SYS-140 #322 (P2).** Follow-up rewrite: ADR-010. `keywords.terms` takes the questions one by one (SYS-140), used by the fallback path.
4. **SYS-141 #323 (P3).** `similarity()` reads `self.vs_l2` once; the docstring states the cosine `1 - d/2`.
5. **DBT-66 #319, DBT-65 #318 (P3).** Four threshold tests; the control character in EXPERIMENTS.md plus a hygiene test over tracked `*.md`.
6. **SYS-137 #316 (P3).** Code guard + store check + the production write (see below).
7. **SYS-138 #317 + SYS-112 #289.** Recency: ADR-012, numbers from the measurement.
8. **SYS-142 #324.** Measurement on production only. No code change until the next planned re-chunk (senior's guidance).
9. **DBT-67 #325.** After QA closes SYS-111 (senior's guidance). Not in this session unless QA closes SYS-111 first.

## SYS-137 detail

- **Guard (code):** `save_chunk_data`'s dedup treats a stored `(sitemap_id, 2)` level as final only when none of its rows is longer than `CHUNK_MAX_TOKENS`. A stale level is replaced: its rows and vectors are removed and the new chunks are inserted. This happens inside the source's deferred block, like SYS-54's discard. L1 is untouched; it has no word cap.
- **Store check:** `check_store_consistency.py` gets `l2_over_max_tokens` (L2 rows over `CHUNK_MAX_TOKENS`, all rows). Baseline 0 after the write, and growing = alert, as for the other checks.
- **Production write (owner-approved 2026-10-12):** pg_dump + FAISS backup, run lock held, between the 19:00 crawl and 07:00.
  - (a) Re-chunk the articles that already adopted stale chunks (2,012 L2 rows on 536+ VIVA articles) with `rechunk_stale_chunks.py`.
  - (b) Delete the chunk rows and vectors of sitemaps with no article row whose L2 rows exceed the cap (7,193 + 230 rows).
  - Done-when SQL: both counts 0.

## Testing strategy (all tickets)

- Unit first, then integration (`tests/integration`, needs the test DB). A new seam gets one test of the composed path (senior's standing observation).
- Every fix gets at least one mutant that re-introduces the bug, registered in `scripts/experiments/qa_mutation_runner.py` and killed in a scratch worktree (venv junction removed before `git worktree remove`, OPS-47).
- RAG changes are measured read-only on production with `probe_rag_rank_breakdown.py --replay --followups` and QA's `probe_topic_switch_followups.py`. Each measurement goes in EXPERIMENTS.md.

## Out of scope

- Showing the rewritten query to the reader (a PM decision; it is logged only).
- Periodic FAISS flushes (owner: soft deadline only).
- Any change to L1 chunks.
