"""QA mutation runner (2026-09-26 audit of HANDOFF_2026-09-26_evening.md).

Applies one textual mutant at a time to the working tree, runs tests/unit with
`-x`, prints KILLED / SURVIVED, and restores the file with `git checkout --`.
Run it on a CLEAN tree only (it restores by checkout, so any uncommitted edit
to a mutated file is lost), and do not import repo code from another process
while it runs -- that process would load the mutant.

Safety: a surviving mutant runs real code paths. The child env points
VECTOR_DB_NAME_L1/L2 at a nonexistent scratch path, POSTGRES_DB_PORT at 1 and
blanks TELEGRAM_BOT_TOKEN, so a survivor cannot touch NEWS_L1/L2, the DB or
Telegram (EXPERIMENTS.md: a mutant once copied the live indexes to backups/).
Scripts that hard-code BACKUP_DIR are not covered by this -- check `backups/`
before and after.

    venv\Scripts\python.exe scripts\experiments\qa_mutation_runner.py            # all mutants
    venv\Scripts\python.exe scripts\experiments\qa_mutation_runner.py NAME ...   # a subset

A pattern is applied only when it occurs exactly once (some files have mixed
line endings; the CRLF form is tried when the LF form is not found).
"""
import os, subprocess, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
SCRATCH = tempfile.mkdtemp(prefix="qa_mutants_")
M = [
 ("starvation_order_by_name", "scripts/run_scheduled_crawl.py",
  "    return sorted(sources, key=key)\n\n\ndef projected_seconds", "    return sorted(sources)\n\n\ndef projected_seconds"),
 ("timeout_for_no_max", "scripts/run_scheduled_crawl.py",
  "return max(default, SOURCE_TIMEOUTS.get(website, 0))", "return SOURCE_TIMEOUTS.get(website, default)"),
 ("timeout_for_ignore_table", "scripts/run_scheduled_crawl.py",
  "return max(default, SOURCE_TIMEOUTS.get(website, 0))", "return default"),
 ("store_note_no_exemption", "scripts/run_scheduled_crawl.py",
  'and not (k == "chunks_not_in_faiss" and counts.get(k, 0) <= pending_sitemaps)]', ']'),
 ("store_note_exempt_all", "scripts/run_scheduled_crawl.py",
  'and not (k == "chunks_not_in_faiss" and counts.get(k, 0) <= pending_sitemaps)]', 'and not (k == "chunks_not_in_faiss")]'),
 ("sample_order_identity", "scripts/check_crawlers.py",
  "    return settled + rest\n", "    return list(articles or [])\n"),
 ("abandon_reason_always_killed", "scripts/run_scheduled_crawl.py",
  '    if status == "timeout":\n        return "killed by', '    if True:\n        return "killed by'),
 ("cascade_min_0", "newscrawler/core/utils/utils.py",
  "CASCADE_MIN_SUFFIX_CHARS = 20", "CASCADE_MIN_SUFFIX_CHARS = 0"),
 ("cascade_min_200", "newscrawler/core/utils/utils.py",
  "CASCADE_MIN_SUFFIX_CHARS = 20", "CASCADE_MIN_SUFFIX_CHARS = 200"),
 ("is_cascaded_ge1", "newscrawler/core/utils/utils.py",
  "return cascaded_pairs(paragraphs) >= 2", "return cascaded_pairs(paragraphs) >= 1"),
 ("is_cascaded_ge3", "newscrawler/core/utils/utils.py",
  "return cascaded_pairs(paragraphs) >= 2", "return cascaded_pairs(paragraphs) >= 3"),
 ("inews_soft_leaves_empty", "newscrawler/core/importance_filter.py",
  '    "INEWS": frozenset({\n        "inews-tv/talkshow",\n    }),', '    "INEWS": frozenset(),'),
 ("url_category_sql_never", "scripts/check_store_consistency.py",
  "WHERE category LIKE 'http%'\")).scalar()", "WHERE false\")).scalar()"),
 ("url_category_not_passed", "scripts/check_store_consistency.py",
  "                              url_category_rows=url_categories,", "                              url_category_rows=0,"),
 ("release_unconditional", "newscrawler/tools/run_lock.py",
  "        if mine:\n            try:\n                os.remove(self.path)", "        if True:\n            try:\n                os.remove(self.path)"),
 ("own_paragraph_is_get_text", "newscrawler/core/utils/utils.py",
  "    parts = []\n    for string in p_tag.strings:", "    return p_tag.get_text(separator).strip()\n    parts = []\n    for string in p_tag.strings:"),
 ("newspaper_parse_unlocked", "newscrawler/infrastructure/datasource/scrapers/crawler.py",
  "            with LXML_PARSE_LOCK:  # SYS-52: newspaper parses with lxml", "            if True:  # SYS-52: newspaper parses with lxml"),
 ("inews_branch_name_returns_url", "newscrawler/infrastructure/datasource/scrapers/inews/inews_crawler.py",
  "        return match.group(1) if match else None", "        return match.group(1) if match else link"),
 ("worker_not_allowed", "newscrawler/tools/run_lock.py",
  "allow_pids=(os.getpid(), os.getppid())", "allow_pids=(os.getpid(),)"),
 ("stale_lock_is_live", "newscrawler/tools/run_lock.py",
  "    return info if live and _is_owner(info, live[1]) else None", "    return info"),
 ("over_budget_uses_default_timeout", "scripts/run_scheduled_crawl.py",
  "                    timeout = timeout_for(website, args.timeout)", "                    timeout = args.timeout"),
 ("log_prune_keeps_all", "scripts/run_scheduled_crawl.py",
  "    for old in (logs[:-keep] if keep > 0 else []):", "    for old in []:"),
 ("null_embedding_ignored", "scripts/run_scheduled_crawl.py",
  "            pending = null_embedding_by_source(session)", "            pending = {}"),
 # --- 2026-09-27: the fixes for the QA list above (SYS-53, OPS-31, DBT-43, SYS-54) ---
 ("sys53_no_generation_check", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.check_fresh(vs, db_name)\n", "            pass\n"),
 ("sys53_no_save_lock", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "        with index_generation.save_lock(db_name):\n            # OPS-26",
  "        import contextlib\n        with contextlib.nullcontext():\n            # OPS-26"),
 # Re-targeted after SYS-60: a save tracks the generation it committed.
 ("sys53_own_save_not_tracked", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.track(vs, db_name, committed)\n", ""),
 ("sys53_load_records_disk_at_save_time", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "    if disk_generation(db_name) != recorded[1]:", "    if False:"),
 ("sys53_no_reload_after_refusal", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            self._reload(db_name)\n            raise", "            raise"),
 ("sys53_refused_ids_kept", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "                self.__dict__.pop(\"_pending_embedding_ids\", None)\n", "                pass\n"),
 # Renamed 2026-09-27 from sys53_run_lock_outside_save_lock: it deletes the call (DBT-47).
 ("sys53_run_lock_check_deleted", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            refuse_foreign_writer()\n            # SYS-56", "            # SYS-56"),
 # DBT-47 (#195): QA's runlock_truly_moved -- the check above the save lock, not inside it.
 ("sys53_run_lock_moved_outside_save_lock", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "        with index_generation.save_lock(db_name):\n            # OPS-26",
  "        refuse_foreign_writer()\n        with index_generation.save_lock(db_name):\n            # OPS-26"),
 ("ops31_access_denied_escapes", "newscrawler/tools/run_lock.py",
  "    except psutil.AccessDenied:\n", "    except ZeroDivisionError:\n"),
 ("ops31_link_is_replace", "newscrawler/tools/run_lock.py",
  "                os.link(tmp, self.path)", "                os.replace(tmp, self.path)"),
 ("ops31_no_create_time_recorded", "newscrawler/tools/run_lock.py",
  "payload = json.dumps({\"pid\": os.getpid(), \"create_time\": _process(os.getpid())[1],",
  "payload = json.dumps({\"pid\": os.getpid(),"),
 ("ops31_legacy_lock_never_stale", "newscrawler/tools/run_lock.py",
  "    return created <= written + CREATE_TIME_SLACK_S", "    return True"),
 ("dbt43_pending_embeddings_unguarded", "scripts/backfill_pending_embeddings.py",
  "    if not args.dry_run and refused_by_run_lock(logger):", "    if False:"),
 ("dbt43_process_event_unguarded", "newscrawler/application/api/lambda_function/lambda_handler.py",
  "    if task in FAISS_WRITING_TASKS:", "    if False:"),
 # SYS-57 replaced the in-memory candidates with a per-source sweep of the store; these two
 # are the same guards over the new code (the end-of-run sweep, and its place after the
 # fetch failures are counted, so a failure that reached the cap is terminal).
 ("sys54_service_never_discards", "newscrawler/domain/services/crawler_service_impl.py",
  "        self._discard_terminal_embeddings(website_name, \"settled terminal this run (SYS-54)\")\n",
  ""),
 ("sys54_failed_fetches_not_candidates", "newscrawler/domain/services/crawler_service_impl.py",
  "        self._source_failure_verdict = self._record_fetch_failures(website_name, attempted, run_failures)\n"
  "        # After _record_fetch_failures, so a failure that reached the cap counts.\n"
  "        self._discard_terminal_embeddings(website_name, \"settled terminal this run (SYS-54)\")\n",
  "        self._discard_terminal_embeddings(website_name, \"settled terminal this run (SYS-54)\")\n"
  "        self._source_failure_verdict = self._record_fetch_failures(website_name, attempted, run_failures)\n"),
 ("sys54_rows_before_flush", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "        if self.chunk_faiss_datasource.is_deferred:\n            self.__dict__.setdefault",
  "        if False:\n            self.__dict__.setdefault"),
 # Re-targeted after SYS-58: a failed flush deletes the rows of its discards instead of keeping them.
 ("sys54_refused_flush_still_deletes_rows", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "                self.__dict__.setdefault(\"_unsaved_discards\", set()).update(\n"
  "                    self.__dict__.pop(\"_discarded_sitemaps\", set()))\n",
  "                self._delete_discarded_chunk_rows()\n"),
 ("sys54_discard_not_flushed", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            if self.is_deferred:\n                self._dirty().add(db_name)\n            else:\n                self._persist(vs, db_name)\n            deleted",
  "            deleted"),
 # --- 2026-09-27 night: the QA list of 44df5b7 (SYS-56..58, OPS-32/33, DBT-47) ---
 ("sys56_load_does_not_roll_forward", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "        recover(db_name)\n        generation = disk_generation(db_name)", "        generation = disk_generation(db_name)"),
 ("sys56_load_skips_pair_check", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "    if problem:\n        raise CorruptIndexError(", "    if False:\n        raise CorruptIndexError("),
 # Re-targeted after SYS-60: commit_staged returns the generation; the caller rolls forward.
 ("sys56_swap_file_by_file", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "    os.rename(staged, journal_dir(db_name))\n    return committed",
  "    os.makedirs(db_name, exist_ok=True)\n"
  "    for name in INDEX_FILES:\n        os.replace(os.path.join(staged, name), os.path.join(db_name, name))\n"
  "    return committed"),
 # Re-targeted after SYS-60 removed SYS-59's owner comparison.
 ("sys56_save_does_not_roll_forward", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.recover(db_name)\n            # SYS-53 (#182)", "            # SYS-53 (#182)"),
 ("sys56_has_index_ignores_journal", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  " or os.path.isdir(journal_dir(db_name))", ""),
 ("sys56_bak_not_in_the_commit", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "    return tuple(name + BACKUP_SUFFIX for name in INDEX_FILES) + (ENCODER_FILE,) + INDEX_FILES",
  "    return (ENCODER_FILE,) + INDEX_FILES"),
 ("sys57_no_sweep_when_the_block_opens", "newscrawler/domain/services/crawler_service_impl.py",
  "            self._discard_terminal_embeddings(website_name, \"an earlier run settled terminal (SYS-57)\")\n", ""),
 ("ops32_faiss_model_by_hub_id", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "model_name=resolve_model(EMBEDDING_MODEL_HF),", "model_name=EMBEDDING_MODEL_HF,"),
 ("ops32_probe_by_hub_id", "newscrawler/core/importance_filter.py",
  "SentenceTransformer(resolve_model(self.model_name))", "SentenceTransformer(self.model_name)"),
 ("ops32_newsletter_by_hub_id", "newscrawler/core/newsletter_generator.py",
  "SentenceTransformer(resolve_model(EMBEDDING_MODEL_HF))", "SentenceTransformer(EMBEDDING_MODEL_HF)"),
 ("ops32_refs_main_ignored", "newscrawler/core/utils/hf_cache.py",
  '        snapshot = os.path.join(folder, "snapshots", revision)\n',
  '        snapshot = os.path.join(folder, "snapshots", sorted(os.listdir(os.path.join(folder, "snapshots")))[0])\n'),
 ("ops32_no_breaker", "scripts/run_scheduled_crawl.py",
  "                    if failed_starts >= FAILED_STARTS_BEFORE_STOP:", "                    if False:"),
 ("ops32_breaker_never_resets", "scripts/run_scheduled_crawl.py",
  'failed_starts = failed_starts + 1 if status == "init_failed" else 0',
  'failed_starts = failed_starts + (status == "init_failed")'),
 ("ops32_init_failure_reads_as_the_source", "newscrawler/tools/source_worker.py",
  'return "init_failed", "crawler could not start', 'return "failed", "crawler could not start'),
 ("ops32_no_retry", "scripts/notify_telegram.py",
  "    for delay in RETRY_DELAYS:\n", "    for delay in ():\n"),
 ("ops32_never_queued", "scripts/notify_telegram.py",
  "            if not ok and retryable and queue_on_failure:\n", "            if False:\n"),
 ("ops32_queue_not_delivered_first", "scripts/notify_telegram.py",
  "            pending = _flush_outbox()\n", "            pending = []\n"),
 ("ops32_refusal_queued_forever", "scripts/notify_telegram.py",
  "    retryable = response.status_code == 429 or response.status_code >= 500\n", "    retryable = True\n"),
 ("ops33_exception_not_redacted", "scripts/notify_telegram.py",
  'return False, True, f"{type(e).__name__}: {redact(e)}"', 'return False, True, f"{type(e).__name__}: {e}"'),
 ("ops33_body_not_redacted", "scripts/notify_telegram.py",
  "{redact(response.text[:500])}", "{response.text[:500]}"),
 ("sys58_failed_flush_forgets_discards", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "                self.__dict__.setdefault(\"_unsaved_discards\", set()).update(\n",
  "                set().update(\n"),
 ("sys58_unsaved_discards_not_redone", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "                if outermost:\n                    self._redo_unsaved_discards()\n", ""),
 ("sys58_redo_keeps_rows", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "        self.__dict__.setdefault(\"_discarded_sitemaps\", set()).update(unsaved)\n        del self.__dict__",
  "        del self.__dict__"),
 ("sys58_redo_rows_without_vectors", "newscrawler/infrastructure/repositories/dataflow/data_flow_repository_impl.py",
  "        self.chunk_faiss_datasource.discard(unsaved)\n", ""),
 # SYS-60 (2026-09-28) replaced SYS-59's owner file, and these replace its two mutants.
 ("sys60_tracks_only_after_its_own_roll_forward", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.track(vs, db_name, committed)\n            index_generation.roll_forward(db_name)\n",
  "            index_generation.roll_forward(db_name)\n            index_generation.track_disk(vs, db_name)\n"),
 ("sys60_committed_generation_unknown", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  "    committed = disk_generation(staged)\n", "    committed = None\n"),
 ("sys60_save_leaves_its_journal", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.track(vs, db_name, committed)\n            index_generation.roll_forward(db_name)\n",
  "            index_generation.track(vs, db_name, committed)\n"),
 ("sys60_any_journal_is_mine", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            index_generation.recover(db_name)\n            # SYS-53 (#182)",
  "            if index_generation.roll_forward(db_name):\n                index_generation.track_disk(vs, db_name)\n"
  "            # SYS-53 (#182)"),
 ("sys56_store_check_drops_mismatch", "scripts/check_store_consistency.py",
  "pair_mismatch_levels=sum(1 for p in (l1_problem, l2_problem) if p))", "pair_mismatch_levels=0)"),
 ("sys62_count_everything_below_the_ratio", "newscrawler/domain/services/crawler_service_impl.py",
  "        return self._record_transient_failures(website_name, attempted, by_class[self.FAILURE_TRANSIENT])\n",
  "        for reason, ids in by_class[self.FAILURE_TRANSIENT].items():\n"
  "            self.data_flow_repo.increment_fetch_failures(ids, error_msg=reason)\n"),
 ("sys62_repeat_never_strikes", "newscrawler/domain/services/crawler_service_impl.py",
  "            repeat = [sid for sid in ids if self._failure_class(prior.get(sid)) == self.FAILURE_TRANSIENT]\n",
  "            repeat = []\n"),
 ("sys62_any_prior_error_is_a_repeat", "newscrawler/domain/services/crawler_service_impl.py",
  "            repeat = [sid for sid in ids if self._failure_class(prior.get(sid)) == self.FAILURE_TRANSIENT]\n",
  "            repeat = [sid for sid in ids if prior.get(sid)]\n"),
 ("sys62_5xx_not_transient", "newscrawler/domain/services/crawler_service_impl.py",
  "TRANSIENT_HTTP_STATUSES = frozenset({403, 408, 429}) | frozenset(range(500, 600))",
  "TRANSIENT_HTTP_STATUSES = frozenset({403, 408, 429})"),
 ("sys62_page_failures_not_struck", "newscrawler/domain/services/crawler_service_impl.py",
  "        for reason, ids in by_class[self.FAILURE_PAGE].items():\n"
  "            self.data_flow_repo.increment_fetch_failures(ids, error_msg=reason)\n", ""),
 ("sys62_transient_not_stamped_source_wide", "newscrawler/domain/services/crawler_service_impl.py",
  "for cls in (self.FAILURE_TRANSIENT, self.FAILURE_PAGE)", "for cls in (self.FAILURE_PAGE,)"),
 # DBT-48 (#199): QA's two survivors of 2026-09-28.
 ("dbt48_new_msg_jumps_queue", "scripts/notify_telegram.py",
  "            if pending:\n                ok, retryable, reason = False, True,",
  "            if False:\n                ok, retryable, reason = False, True,"),
 ("dbt48_cli_message_queued", "scripts/notify_telegram.py",
  "    ok = send(text, queue_on_failure=False)\n", "    ok = send(text)\n"),
 # SYS-61 (#198): the encoder revision the probe and the FAISS pair were built with.
 ("sys61_probe_revision_unchecked", "newscrawler/core/importance_filter.py",
  "        if model is None:\n            self._check_encoder_revision()\n", ""),
 ("sys61_probe_missing_revision_accepted", "newscrawler/core/importance_filter.py",
  "        if not self.probe.encoder_revision:\n            raise ProbeArtifactError(",
  "        if False:\n            raise ProbeArtifactError("),
 ("sys61_faiss_encoder_unchecked", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "            self._check_encoder(db_name)\n", ""),
 ("sys61_faiss_model_unchecked", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "        if recorded.get(\"model\") != loaded.get(\"model\"):", "        if False:"),
 ("sys61_encoder_not_rolled_forward", "newscrawler/infrastructure/datasource/dataflow/write/faiss/index_generation.py",
  " + (ENCODER_FILE,) + INDEX_FILES", " + INDEX_FILES"),
 ("sys61_crawl_saves_without_encoder", "newscrawler/infrastructure/datasource/dataflow/write/faiss/chunk_faiss_data_source.py",
  "self._atomic_save_local(vs, db_name, encoder=self.encoder_record)", "self._atomic_save_local(vs, db_name)"),
 ("sys61_trainer_cache_ignores_revision", "scripts/train_importance_probe.py",
  "    key = hashlib.sha256((encoder + revision + sha256_of_file(gold_path)",
  "    key = hashlib.sha256((encoder + sha256_of_file(gold_path)"),
]
only = sys.argv[1:]
env = dict(os.environ, VECTOR_DB_NAME_L1=os.path.join(SCRATCH, "NOPE_L1"),
           VECTOR_DB_NAME_L2=os.path.join(SCRATCH, "NOPE_L2"), POSTGRES_DB_PORT="1",
           TELEGRAM_BOT_TOKEN="", PYTHONDONTWRITEBYTECODE="1")
for name, path, old, new in M:
    if only and name not in only: continue
    p = os.path.join(ROOT, path)
    src = open(p, "rb").read().decode("utf-8")
    crlf = "\r\n" in src
    o, n = (old.replace("\n", "\r\n"), new.replace("\n", "\r\n")) if crlf and src.count(old) != 1 else (old, new)
    if src.count(o) != 1:
        print(f"{name}: PATTERN NOT FOUND ({src.count(o)})", flush=True); continue
    open(p, "wb").write(src.replace(o, n).encode("utf-8"))
    try:
        r = subprocess.run([r"venv\Scripts\python.exe", "-m", "pytest", "tests/unit", "-q", "-x", "-p", "no:cacheprovider",
                            "--no-header", "-rN", "--tb=no", "-W", "ignore"], capture_output=True, text=True, env=env, cwd=ROOT)
        tail = [l for l in r.stdout.splitlines() if l.strip()][-2:]
        print(f"{name}: {'KILLED' if r.returncode else 'SURVIVED'} rc={r.returncode} :: {' | '.join(tail)[:300]}", flush=True)
    finally:
        subprocess.run(["git", "checkout", "--", path], cwd=ROOT)
