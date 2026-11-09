# Staff Engineer — QA's 2026-10-13 queue (2026-10-19)

- **One definition per concept.**
  - The -nya rules move out of `followup.py` into `web/nya_words.py`. `followup` and `keywords` both import them, and
    no copy is left behind (test).
  - The "terminal" rule moves into `store_repair` (DBT-70). A test pins that no script imports a toolkit script, not
    only the toolkit scripts themselves.
- **Reuse:** `story_words.names` / `story_words.vocabulary` are the newsletter's names definition (months, titles, digit
  tokens excluded). Reused for "the follow-up's own subject"; no third name rule.
- **Tests:**
  - every ticket gets the QA file's cases, plus their unit equivalents in `tests/unit`;
  - each fix's mutants are registered in `scripts/experiments/qa_mutation_runner.py` and run in a copy
    (`run_registry_mutants_in_copy.py`), never in the main tree (the scheduled jobs import it).
- **Measurement before claims:**
  - `measure_name_gate.py` / `measure_nya_terms.py` are re-run on the real code (not the patched candidate);
  - `probe_rag_rank_breakdown.py --replay` is run twice after SYS-194 (identical), then once with the rest;
  - every probe is read-only.
- **Scheduling:** crawl 07:00/19:00 imports the DTO and the store check, newsletter 12:00, extraction 21:00. Edits to
  crawl-imported files land green, or after the 07:00 run's workers are done. Web files are imported only by uvicorn,
  which the owner restarts.
