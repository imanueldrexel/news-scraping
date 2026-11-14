# SDE: QA's 2026-11-11 qa-defects (2026-11-15)

On local `dev` on top of 99d92a8. Red commit 1c8c234 holds QA's four tests unchanged (`tests/unit/test_qa_1111_defects.py`, 14 failing). Pushed to `origin/dev`, and a dev -> main PR was opened (#335 was merged).

## Built
- **#458 (SYS-186, parent #387, major):** `source_check._ends`. When "pada" follows, a name in the gap is a place after a spread verb or "dari <name>", as at d76b5ea. Before a month with no "pada", it is a place only after a spread verb or in a bare range of places, where every word after "dari" is a name (`_from_place(range_only=True)`).
  - "dari Sabang hingga Merauke akhir Oktober" stays a place (#453).
  - "dari MSCI berlaku hingga Review November 2026" is an end again.
- **#459 (SYS-191, parent #392):** `_stated_completions` skips a time-first completion when a shift word, followed by up to two words, stands before the time (`_SHIFTED`).
  - The shift list is shared with the gap as `_SHIFT`, which now also holds sesudah and melewati.
- **#460 (SYS-189, parent #390):** `build_word_classes._CONNECTIVES = {"sejalan"}`, and "sejalan" is removed from `movement_words.txt` (155 -> 154 words). There was no rebuild: the rest of the snapshot is the same.
- **#461 (SYS-203, parent #457):** `story_arc._trim` drops `_whole_sentences`: `arc_style.sentences` pieces are re-joined after an initial ("R."), a dotted initialism ("M.H.", "s.d.") or a listed abbreviation (No., Prof., Dr., Jl., Tbk., dkk., dll., ...).
  - `arc_style.sentences` is unchanged. QA left its other callers out of scope.
  - A lower-case or digit continuation rule was tried and dropped: it broke `test_newsletter_arcs`' SYS-203 fixture, and QA's cases do not need it.
- **QA's REPAIRABLE gate gap (2026-11-11 report):** `TestRepair.test_the_gate_itself_refuses_a_fact_reason` hands `repair` an answer a length trim fixes, under each fact reason. Mutant `sys203g_repairable_facts` is killed.

## Verification
- QA's 14 cases go from failing to passing. Own tests: `test_source_check.TestQa1111EndPoints`, `test_causal_check` (snapshot + builder), `test_story_arc.TestRepair` (splitter + gate).
- Mutants: 23/23 killed in a copy: 8 retargeted after the `_ends` / `_SHIFT` rewrite, 11 new (`sys186g_`, `sys191g_`, `sys189g_`, `sys203g_`), and the 4 untouched `sys186d_` / `sys191f_` neighbours.
- End points of 677 digest sentences at 1c8c234 vs the fix: 0 differences.
- Connectives after a needs-cause verb, 84c3567 vs HEAD (EXPERIMENTS 2026-11-15): only "sejalan" is a causal synonym that regressed.
- Unit: 4,416 passed / 5 skipped. `tests/qa`: 55 -> 32 failing, 0 new. Integration was not run: no DB code or migration changed.

## Not done / left open
- **#458 residual:** "Diskon dari Garuda Indonesia hingga Lebaran Maret 2027" (dari <names> directly before hingga, then a name and a month) still reads as a range of places. It cannot be told from "dari Sabang hingga Merauke akhir Oktober" by shape. Neither QA's cases nor the archive have it.
- **#460 residual:** didukung / mengingat / menyusul / merespons after a needs-cause verb were kept at 84c3567 too. They are pre-existing gaps that ADR-031 accepts.
- **Ledgers:** `ticket.py init` refuses all four parents (no AC lines, no Done-when). Writing criteria for legacy tickets is the owner's or QA's work.
- **Next in the queue (PM 11-14):** SYS-204 (#462), SYS-205 (#463), SYS-206 (#464) + SYS-201 (#455).
