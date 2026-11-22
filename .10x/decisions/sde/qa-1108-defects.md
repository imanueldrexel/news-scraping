# SDE: QA's 2026-11-08 qa-defects (2026-11-10)

On local `dev` on top of d76b5ea, not pushed. As in earlier rounds, QA audits local commits; #335 is the stale dev -> main PR.

## Built
- **#450/#451 (SYS-144/145):** `followup._opening_subject` reads an opening word as no subject only when it is in `_SHARED_OPENERS`.
  - That set is a closed class: time words, particles, hedges, modal and aspect adverbs, connectives and pronouns.
  - The old test was "any common word", which caught nouns too.
  - `common_words.txt` still decides the -kah form.
  - ADR-032 amended.
- **#452 (SYS-189):** `scripts/build_word_classes.py` now:
  - admits no possessed -nya noun (`nya_words.is_reference`);
  - skips a capitalised word after a lower-case verb (headings with no stop), but keeps title-case headings;
  - drops "terjun" (as in "terjun payung").

  `movement_words.txt` was rebuilt: 176 -> 155 words, removals only. `common_words.txt` was left at its 11-07 snapshot; the rebuild's diff there is corpus drift.
- **#453 (SYS-186):** `source_check._ends`: a name in the gap is a place before "pada" or before a month or date. Before a bare year it is a named time ("Lebaran 2027").
- **#454 (SYS-191):** `_stated_completions` lets a source state a completion in other words: up to 2 gap words, or the time before the verb. It never counts a negated completion, nor one shifted by setelah/sebelum/paling lambat. It backs only a prose `_END_CLOSE` (named group `close`).

## Verification
- QA's tests are copied unchanged into `tests/unit/test_qa_1108_defects.py`.
- Inverse probes:
  - `test_followup.TestQa1108CommonNounSubjects`;
  - `test_source_check.TestQa1108EndPoints`;
  - `test_causal_check`: the class holds no possessed noun; "hanya" and "sepekan" are not causes.
- Diffs across 84c3567, HEAD and now, in `git archive` copies:
  - 207 follow-up routings: only the intended changes;
  - 33 end-point probes and the end points of 328 arc sentences: 0 arc readings changed.
- Mutants: 26/26 killed in a copy.
  - 13 new: `sys144f_`, `sys189f_`, `sys186f_`, `sys191f_`.
  - 8 retargeted after the refactor: `sys186e_place_without_pada`, `sys191e_no_diselesaikan`, `sys191d_no_rampung/no_ditutup`, `sys186_any_shared_part_backs`, `sys186_precise_prose_backed`, `sys193_no_subject`, `sys193_subject_always_needed`.
- Unit 4,331 passed / 5 skipped. Integration 229 / 1 skipped. `tests/qa`: 50 -> 27 failing, 0 new.

## Not done / left open
- **#425:** replay re-run 2026-11-10 04:43. Still `ExceededBudget Spend=61.50 Budget=61.5`. #338 stays qa-failed.
  - *Update, after the owner's top-up:* SYS-202 (#456) was found and fixed (334ecdc): the provider ignores `thinking: disabled`, and `reasoning_effort="none"` is now sent.
  - The replay then gave 13/20 = 65%. SYS-203 (#457) is filed, length trim first.
- **SYS-201 (#455), filed, not fixed:** a negated stated end ("belum diselesaikan pada") backs a prose end. Pre-existing, out of these defects' scope.
- **IEU-CEPA arc sentence:** still refused against its real source. SYS-193's per-sentence subject rule applies: the completion sentence names no IEU-CEPA.

## Tech debt
- `_SHARED_OPENERS` is a hand list, but of a closed class; a test holds it inside `common_words.txt`. An opener it lacks is read as a subject, which was the pre-9d9ad16 behaviour.
