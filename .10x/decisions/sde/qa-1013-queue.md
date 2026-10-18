# SDE — QA's 2026-10-13 queue (built 2026-10-19)

Commits:
- `e6637a9`: SYS-144/145 send-back, SYS-146 (ADR-021), SYS-194;
- `6c934c0`: DBT-60 send-back, DBT-70, DBT-71, SRC-62.

Design: ADR-021, `architect/qa-1013-queue.md`. Each commit passes tests/unit on its own (checked on an archive export of
e6637a9).

## What was built
- **`newscrawler/web/nya_words.py` (new, pure):**
  - `ADVERBS` (53: SYS-144's 22, QA's held-out 6, 25 read by hand from `sys144/mine_nya_adverbs.py`) and
    `NOT_CLITIC`;
  - `is_reference(word)` and `possessive_root(word)` (root of 3+ letters; "buyback-nya" → "buyback"; "Kenya" kept).
- **`followup.py`:**
  - `_references(q)` and `refers_back(q)` (lexical, as before, list from nya_words);
  - new `refers_to_thread(q, previous)` (ADR-021). Both `resolve` paths use it: kept → kept-thread, fallback →
    fallback-thread;
  - `_OBJECT_PHRASE` = ke/kepada/terhadap/bagi/untuk/pada/di/atas + up to 4 words;
  - **the FIRST reference decides** (the design runs used the last; identical on every measured pair, and "first"
    is the logically right reading: an unresolved first reference points into the thread). Pinned by
    `test_the_first_reference_decides`.
- **`keywords.terms`:** an ADVERBS word is skipped; `possessive_root(low) or low` replaces the word before the
  stopword and duplicate checks. The name flag is read on the word as written.
- **`query_processor._fts_sql`:** `, c.chunk_id DESC` closes both ORDER BY forms (SYS-194).
- **`site_map_dto.posted_at_datetime` + `_as_number`:**
  - any `numbers.Real` or Decimal, and any string Decimal() parses, is a yyyymmdd when integral and 8 digits;
    otherwise ValueError;
  - a non-finite value raises (int(Infinity) would raise OverflowError, which pydantic does not turn into a
    ValidationError);
  - a bool still returns early, so pydantic refuses it.
- **`store_repair.sitemap_state(session, ids)`:** OPS-25's "terminal", moved from `repair_store_consistency._load_state`.
  Both scripts import it.
- **INVESTORID:**
  - `_SECTION` + `re.match` → the section or None;
  - `SOURCE_SOFT_LEAVES["INVESTORID"] = {"money-lab"}`; `SOFT_BRANCH_DENY` points at it.

## Deviations from plan
- The senior plan listed `utamanya` and `rasanya` as adverbs; they were kept as references ("tujuan utamanya",
  "bagaimana rasanya"). They are named in nya_words' docstring.
- DBT-60: `.strip()` removed, because Decimal() ignores surrounding whitespace. QA's `qa1013_dbt60_no_strip` was
  retired as equivalent (noted in the registry). QA's `qa1013_dbt60_bool_is_a_date` is no longer equivalent and is
  now KILLED (`test_the_dto_refuses_unix_seconds_and_a_bool`).
- Two experiment scripts became before/now tools:
  - `measure_name_gate.py` holds the old 26-word list as `OLD_NOT_REFERENCES`;
  - `measure_nya_terms.py` switches the nya rules off for "before".

## Verification
- Unit 3,879 passed / 5 skipped; integration 225 passed / 1 skipped.
- QA file `qa_2026_10_13/test_qa_audit.py`: every SYS-144 (6), SYS-145 (6), DBT-60 (6) and DBT-67/70 (1) red is green.
  - Still red at HEAD and before: SYS-143's 5 held-out refusal shapes (QA: noted, not filed).
  - In an export without .git: DBT-68's git-ls-files test.
- Mutants, in a copy: 22 follow-up/keyword (9 new sys144b, 4 sys146, 1 sys194; sys104/144/145/qa1013 retargeted),
  6 + 3 DBT-60, 2 DBT-70, 3 SRC-62, QA's 4 DBT-71/68: **all KILLED**.
  - Two (`sys144b_kept_path_lexical`, `sys144b_fallback_lexical`) survived the first test set, because its resolve
    test used an adverb now on the list. Fixed with an inner-reference and an unlisted-adverb case.
  - The DBT-70/SRC-62 runs' copy baseline has 6 git-dependent failures. Every mutant there failed 8-12, so all are
    real kills.
- Production probes (read-only): EXPERIMENTS.md 2026-10-19 entries (SYS-194, ADR-021, SRC-62).

## Tech debt / follow-ups
- SYS-195 #397: off-subject semantic hits outrank keyword hits that hold the question's name. It keeps "Siapa
  pemimpinnya Danantara?" at 2/5, and SYS-146's Done-when lists it.
- The 90 stored INVESTORID money-lab rows keep category `news`; 18 of them are saved explainers. Re-labelling or
  removing them is a production write: owner's call.
- SYS-143's held-out refusal shapes stay as QA left them (not filed).

## Security
- No new input surface. The follow-up regexes are linear: `_OBJECT_PHRASE` is bounded at 4 tokens, and questions are
  already capped upstream. No SQL text is built from question words (SYS-194 adds a column name to fixed SQL).
