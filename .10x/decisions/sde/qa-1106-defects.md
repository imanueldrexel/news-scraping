# SDE: QA's 2026-11-06 qa-defects (2026-11-07/08)

Commit 4175812 on local `dev` (not pushed, as in earlier rounds: QA audits local commits).

## Built
- **ADR-032: two word classes from the archive.** `scripts/build_word_classes.py` is read-only and covers 202,635 articles.
  - `newscrawler/web/common_words.txt`: 39,404 words written in lower case where no sentence starts.
  - `newscrawler/core/movement_words.txt`: 176 words that follow a market-movement verb at least 3x as often as a cause marker.
  - Both load through `story_words.read_words`.
- **#448/#449 (SYS-144/145):** `followup._opening_subject` reads the opening word as a subject only when it is not a common word (stem under -kah included).
- **#421/#422/#423 held out:** `nya_words.in_adverb_place` (`_OWN_CLAUSE_AFTER`). A word is in adverb place when it is followed by a comma and an interrogative, the next word is no stopword, and the clause names a name.
- **#440 (SYS-189):** `causal_check._cause_follows`: movement words are no cause; past them, a cause is read only after "oleh".
- **#446 (SYS-186):** `source_check._ends`: a gap that opens on a name is a place only when "pada" joins the time.
- **#445 (SYS-191, owner-narrowed):** `_END_CLOSE` adds "diselesaikan".

## Verification
- QA's tests, unchanged, are in `tests/unit/test_qa_1106_defects.py`. #445 has only the owner's narrowed case plus the controls.
- Inverse probes sit in each module's test file (`TestQa1106*`).
- Mutants: 32/32 KILLED in a copy (`%TEMP%\claude\mutcopy1107`). 6 were retargeted and 10 are new (`sys144e_`, `sys189e_`, `sys186e_`, `sys191e_`). `sys189e_name_is_movement` was equivalent, so its guard was removed.
- Suites: unit 4,271 passed / 5 skipped; integration 229 / 1 skipped.
- Pure HEAD-vs-now checks:
  - routing of 65 probe pairs: 0 changed;
  - causal readings of arc-output sentences: unchanged;
  - `tests/qa/`: only FAILED -> PASSED.

## Not done
- **#425 (SYS-148):** the replay was blocked by SumoPod's key budget (`ExceededBudget, Spend=61.50, Budget=61.5`). Parent #338 stays qa-failed until the owner raises the cap and the replay is re-run.

## Tech debt / deviations
- The word files are snapshots. Rebuild them on purpose and review the diff.
- Accepted costs:
  - names that the archive mostly writes in lower case (Emas, Bank) read as common;
  - a cause after a movement word without "oleh" is unchecked.
- `replay_story_arcs.py` crashes (AttributeError) when the provider fails for a whole date. Not ticketed: it is an experiment script, and the cause was a one-off account cap.
- The pasted SDE rule says push or open a PR. Not done, by the owner's standing choice of local-commit review.
