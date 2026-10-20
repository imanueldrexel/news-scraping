# qa-1019-sendbacks — dev fixes for QA's 2026-10-19 qa-defects (#398-#412)

**Date:** 2026-10-20 · **ADRs:** ADR-022 (follow-up), ADR-023 (arc guards)

## Per defect
| Defect | Parent | Status | Root cause | Fix |
|---|---|---|---|---|
| #398 | SYS-181 #381 | FIXED | `_refers_back` lent the whole previous sentence when the anaphor's subject shared ANY root with it | every subject word after its head must be named (`_named`, suffix-tolerant); `_lent` borrows only the parts (clause/"dan") that hold them |
| #399 | SYS-185 #385 | FIXED | `_DENIAL` searched `before_text` only | searched over `sentence[left:right]` |
| #400 | SYS-185 #385 | FIXED | no sangkal family; `(?:me|di)nepis` / `(?:di|me)nampik` missed ditepis/ditampik | listed; frame words too |
| #401 | SYS-189 #390 | FIXED (dipacu, terdorong, buntut + terpacu) / DISPUTED (terimbas) | closed table | table + prompt + FORMS; terimbas conflicts with SYS-184's `test_affected_is_no_link` |
| #402 | SYS-192 #393 | FIXED | closed hedge list | estimate/belief/rumour verbs with active forms; nouns perkiraan/proyeksi excluded |
| #403 | SYS-191 #392 | FIXED | stop verbs and deadlines unread | `_END_OPEN` + diakhiri/berhenti/terhenti/dihentikan; `_DEADLINE` kind: a source deadline backs only a prose deadline |
| #404 | SYS-193 #394 | FIXED | fronted end had an empty subject -> time alone | subject = clause after the time when the clause before is empty |
| #405 | SYS-193 #394 | DISPUTED | — | a 2-noun rule refuses the live MSCI true end ("Freeze ... berlanjut" shares only the verb) |
| #406 | SYS-186 #387 | FIXED | gap read "Riau" as the time's noun | `_ends`: a gap opening on a name after a verb of spread (`_SPREAD`) is no end |
| #407 | SYS-177 #376 | FIXED | cue was a list of forms | plan roots with affixes; QA's past-word flip measured and rejected |
| #408/#409 | SYS-144 #327 / SYS-145 #328 | FIXED | object-phrase masking handed the decision to the adverb list | `_references`: an -nya word right after "yang" is no reference unless a verb (+ list growth) |
| #410 | SYS-145 #328 | FIXED | 4-word cap | object phrase to clause end, stopping before "dan/atau <question word>" |
| #411 | SYS-146 #331 | FIXED (list) | keyword layer is list-based (ADR-021 decision 3) | spoken adverbs added |
| #412 | SYS-146 #331 | FIXED | NOT_CLITIC lacked affixed "tanya" | ditanya/menanya/tertanya/tanya-tanya listed (not a suffix test: "datanya") |

## Deviations / tech debt
- Changed one existing dev test: `TestSys193EndSubject::test_a_clause_with_no_subject_is_matched_by_its_time` pinned the fallback #404 removes; replaced by two tests (stricter, not weaker). Flagged for QA.
- Not fixed, flagged: QA's held-out `TestQaSys185HeldOut[... tanpa dipicu ...]` (red at 8cd85d6 too, not filed).
- `story_words.is_verb` misreads "mesti" as a me- verb; the list covers it.
- Rejected design measured: adjacency-only object phrases (risk 24/30 -> 1/30).
- 15 registry mutants retargeted, 30 new (`*c_*`).

## Evidence (commit 8b45d8f)
- `tests/unit` 3,955 passed / 5 skipped (before the last test, +1); `tests/integration` 225 passed / 1 skipped.
- Web mutants (copy): 23/23 KILLED (sys144*, sys145*, sys146*, incl. 6 new).
- Arc mutants (copy): the run was stopped by Claude Code for low system memory (the scheduled crawl's worker held
  ~7 GB) after 61 entries: 60 KILLED, `sys181_anaphor_off_subject` SURVIVED -> new test
  `TestSys181Anaphor::test_an_anaphor_in_a_fronted_place_lends_nothing`, now KILLED. **Not run:** every new arc
  `*c_*` mutant and the sys177 entries after `sys177_present_unwired`. Re-run with
  `run_registry_mutants_in_copy.py <copy> sys177 sys181c sys185c sys186c sys189c sys191c sys192c sys193c` when
  memory allows.
