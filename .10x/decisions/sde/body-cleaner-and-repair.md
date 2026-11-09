# body-cleaner-and-repair — SDE

### 2026-10-04 (evening) — SYS-75 fixed, SYS-73 dry run done
- **SYS-75 #225** (filed by dev; found by the SYS-73 dry run): `_BOILERPLATE_ANYWHERE` dropped the whole line when `[Gambas:` or `Tautan telah disalin` appeared anywhere, deleting a real paragraph that trailed it (109 stored articles, every new DETIK row). New `clean_line` in `core/utils/utils.py`: a closed widget is cut, the toast/unclosed widget cuts to the end of the line; text before the toast is kept at any length, text around a widget needs `MIN_PROSE_AFTER_WIDGET` (120) characters. `is_boilerplate_line` = `clean_line(...) is None`. 20 tests, 7 mutants killed. Labelled ready-for-qa.
- **SYS-73 #223**: `scripts/repair_boilerplate_bodies.py` is the read-only dry run (the only mode). Result on #223: 35,547 of 84,606 articles would change, 0 emptied, 4 under 200 chars, 1.34% of characters, baca-juga 17.6% -> 0.1%, chrome 24.7% -> 0%, 165,319 of 411,994 chunk rows would be deleted and re-embedded. **The apply path is not written**; it waits for the owner's approval of the report, a backup, and a decision on one job vs per source.
- **DBT-50 #214**: the recount test now uses the script's own `DRIFT_SQL`; 3 mutants killed. Labelled ready-for-qa.

### Known residual (not fixed, recorded on #225)
~7 articles have a related-headline line with the next sentence glued to it without a separator; the line is still removed whole.

### Tech debt created
- The dry run reads all 84,606 bodies in one streamed query (about 100 s); fine for a one-off, not a monitor.

### 2026-10-04 (late evening) — owner decisions, executed
1. **SYS-39 gate: accepted on evidence** (repeatability 0.960, 0 parse failures, $0.32/1,000, reversible env switch, gold-set hand check 96-98%). No hand-check, no Gemini reference. `KNOWLEDGE_LLM_PROVIDER=openai` is still NOT set in `.env`: setting it and scheduling the extraction run are the next steps (off-peak; backlog needs `KNOWLEDGE_DAILY_COST_LIMIT_USD` ~30 for one run).
2. **Production migration applied** after a verified dump (`backups/pg_dump/newsaggregator_20261004T133211Z.dump`, 246 MB): `api_usage_log` has the 3 new columns, 9 existing rows intact.
3. **OPS-38: 12:00, registered** as "NewsAggregator Newsletter" (first run 2026-10-05 12:00, digests 2026-10-04 and replaces the stray partial row).
4. **SYS-73: per source, DETIK first, after QA closes SYS-75.** The apply path is the next code to write (dry-run per source first).

