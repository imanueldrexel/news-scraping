# SDE: dev fixes of QA's second pass (2026-10-12 evening)

Spec: `specs/2026-10-12-qa-second-pass-fixes-design.md`. ADR-013, ADR-014, ADR-015.

## Built
- **SYS-138 #317 (rework, ADR-013)**
  - `KeywordQuery.subject` = the names, else the anchors.
  - `QueryProcessor._holds_subject` is SQL over `to_tsvector('simple')`. It shares `_per_text` with `_coverage`, so there is one unnest query shape.
  - `_window_leaders`: past the floor **and** holding the subject. Keyword-origin hits pass by construction. Without a keyword query, the floor decides. A failed test closes the gate, with a warning.
  - `candidates`: leaders first, then the rest (the window's own ranking when it holds `RAG_TOP_K` leaders, else the unwindowed ranking). The log is unchanged: `7d` / `7d+N`, where N counts leaders now.
- **SYS-143 #326:** `followup.check` rejects a refusal (`_REFUSAL`, anchored at the start) or a list item (`_LIST_ITEM`). The call is still counted (the DBT-69 test).
- **SYS-144 #327:** `_NOT_REFERENCES` holds 22 *-nya* adverbs. There is no `se-…-nya` pattern; tests pin *sesudahnya / setelahnya / sebaliknya* as references.
- **SYS-145 #328 (ADR-014):** `followup.resolve` maps a `kept` rewrite plus `refers_back` to `_with_thread(..., KEPT_THREAD)`. `_with_thread` is shared with the fallback, so the two cannot drift.
- **DBT-69 #330**
  - unit: an unusable reply is counted with its tokens;
  - integration: `--source VIVA` leaves JPNN's queued stale chunks; an 80-word queued L2 row is not a target, an 81-word one is.
- **DBT-68 #329:** the second `TestSoftDeadline` is deleted. `test_repo_hygiene.py::test_no_test_module_shadows_a_test_name` (AST, every tracked `tests/*test_*.py`) plus a self-test of the checker.

## Tests
- New/changed: `test_followup.py` (+26 cases), `test_query_processor_ranking.py` (+4 follow-up, +5 week window incl. picked dates / below floor, + `TestWeekWindowSubjectGate` 8), `test_rag_keywords.py` (+3), `test_rag_keywords_live.py` (+2), `test_drop_oversized_queued_chunks_live.py` (+2), `test_repo_hygiene.py` (+2).
- unit 2924 passed / 5 skipped. Integration: see the ticket comments.
- QA's `test_qa_fixes.py`: 37 pass, 1 fails by its own fixture (explained on SYS-138 and in EXPERIMENTS.md).

## Mutants
- Registered in `qa_mutation_runner.py`: 8 `sys138b_*`, 3 `sys143_*`, 2 `sys144_*`, 2 `sys145_*`, `dbt68_duplicate_class_back`.
- QA's `qa1012b_fill_only_when_empty` and `qa1012b_window_leads_below_floor` are retargeted to the reworked lines.
- Run in `%TEMP%\mutwt` (results on the tickets).

## Deviations
- None from the design.
- QA's Danantara repro test cannot pass under any fix (fixture defect), so a corrected equivalent is in `tests/unit`. QA's file was not edited.

## Noticed, not mine to file (dev files no tickets from testing)
- `tests/integration/test_story_grouping_live.py` has `venv\Scripts` in a non-raw docstring (an invalid `\S` escape: DeprecationWarning, a future SyntaxError). Same class as DBT-42/65.

## DBT-67 #325 (ADR-015): store_repair module, separate commit
- **`newscrawler/tools/store_repair.py`:**
  - steps: `crawl_running`, `parse_until`, `too_close`, `faiss_dirs`, `NoEmbeddings`, `vector_ids_for`, `delete_vectors`, `require_free_disk`, `backup`, `rechunk_articles`, `rechunk`, `recount_entity_counts`;
  - constants: `BACKUP_DIR`, `MIN_FREE_GB_FOR_BACKUP`, `DEFAULT_BLOCK`, `MIN_RUN_MINUTES`, `ORPHAN_ARTICLES_SQL`, `ENTITY_DRIFT_SQL`, `ENTITY_FIX_SQL`;
  - it imports no script and does not touch `sys.path`; its logger is at INFO, as the scripts' are.
- **Scripts, now thin CLIs:**
  - repair_boilerplate_bodies, rechunk_stale_chunks, settle_out_of_scope_links and drop_oversized_queued_chunks import the steps by name (no `scripts/` on `sys.path`);
  - backfill_orphan_chunks and recount_entity_mentions are CLIs over the module;
  - repair_store_consistency and requeue_cascaded_articles drop their own `_crawl_running` copies (2 more drifted copies) and the stub/lookup;
  - `rechunk_stale_chunks.backup_l2` uses `require_free_disk`; settle and the boilerplate repair call `recount_entity_counts(client)` instead of another script's `main([])`.
- **No behaviour change:** the same SQL, write order, backups and log lines. One difference: the recount's backup is under `store_repair.BACKUP_DIR` (the same `backups/` in production; tests redirect one value now).
- **Tests:**
  - patch targets moved (`faiss_dirs`/`crawl_running` public; `store_repair.datetime` for the deadline; `store_repair.BACKUP_DIR` in four integration fixtures; `scripts.rechunk.rechunk`). A stale fixture that still redirects a script's `BACKUP_DIR` now raises `AttributeError` instead of silently writing to `backups/`;
  - `test_entity_counts_live` reads `store_repair.ENTITY_DRIFT_SQL`; `test_repair_boilerplate_bodies_live` picks its `sys73_*` backup folder, since the recount's `sys20_*.json` now shares the redirected directory;
  - new `tests/unit/test_store_repair_module.py`: no toolkit script imports another script (OPS-01's `notify_telegram` excepted, out of scope), the module imports no script, no script keeps its own copy of a step, the scripts call the module's objects, and `BACKUP_DIR` is never copied into a toolkit script;
  - `test_run_lock` writer markers: `delete_vectors(`, `rechunk(`, `rechunk_articles(` replace `import repair_boilerplate_bodies` (the writer set is unchanged).
- **Mutants:**
  - retargeted to the module: `sys109_group_never_batches`, `sys109_failed_group_not_retried`, `sys111_past_deadline_is_today`, `sys111_too_close_never`, `sys111_too_close_at_the_margin`;
  - new: `dbt67_script_imports_a_script`, `dbt67_a_script_copies_a_step`, `dbt67_backup_dir_copied`.
- **For QA:** your first-pass `scripts/experiments/qa_2026_10_12/test_qa_tickets.py::TestSys111DeadlineResolvedOnce` patches `rb._faiss_dirs`/`rb._crawl_running`/`rb.datetime`. After DBT-67 those names are `faiss_dirs`/`crawl_running`, and the clock is `store_repair.datetime`. The same guarantee is `tests/unit/test_repair_boilerplate_bodies.py::TestOneDeadlinePerRun`.

## Security / DBA notes
- `_holds_subject` builds fixed SQL from `_word_tests`. Every question word is a bind parameter (`lexeme`), never SQL text; `TestHoldsSubject` asserts no word appears in the SQL.
- The rewrite's output is still only a search string (ADR-010). The refusal check narrows what is searched; it does not add a channel.
- No schema change and no migration. No production DB or FAISS write this session (probes read-only; 28 rewrite calls, $0.0013).
