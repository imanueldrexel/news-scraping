# SDE: nli-faithfulness (2026-10-25)
## Built (SYS-198 #428, code complete; live evidence pending)
- `core/nli_check.py` (Scorer protocol, `HfScorer` lazy, `best_verdict`, `premise_units`), `core/nli_shadow.py` (gate_tags, build_rows with time budget, record that never raises).
- `scripts/migrate_nli_shadow.sql` registered in `scripts/migrate.py`, CLAUDE.md list; ORM `NliShadowTable`; `save_nli_shadow` (replace-the-day, 90-day retention); constants `NLI_SHADOW` (default 0), `NLI_MODEL`, `NLI_TIME_BUDGET_S`.
- Wired in `NewsletterGenerator._write_edition` AFTER the edition file is written, only when NLI_SHADOW=1 and the edition has arcs.
- Tests: `tests/unit/test_nli_shadow.py` (23), `tests/integration/test_nli_shadow_live.py` (3). Unit suite 3979 passed / 5 skipped; integration schema + shadow 7 passed on newsaggregator_test. 7 hand mutants all killed (alur premises, budget, swallow, no-model guard, argmax, scorer-failure, miscount).
## Built (SYS-197 #427, offline part)
- `scripts/experiments/eval_nli.py` + `tests/fixtures/nli_eval/golden.jsonl` (12 pairs) + `tests/unit/test_eval_nli.py` (8). No pair generation yet (spends money; waits on the owner).
## Deviations
- v1 hypothesis is the whole sentence (spec 4.1 said minimal proposition when a gate fired); sentence + premise ids are stored so SYS-199 re-scores propositions offline.
- Model arm A: MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (smoke-tested, EXPERIMENTS.md 2026-10-25).
## Found
- venv torch is 2.8.0+cpu: no CUDA. Fine for scoring; arm B fine-tuning needs a CUDA build (changes the venv; owner decision + requirements.txt regeneration).
## Tech debt
- gate_tags imports causal_check privates (_causal_matches, _HEDGE, _DENIAL); SYS-196's lexicon will replace them, switch then.
## Not done
- Prod migration (owner backup/approval), one live 12:00 edition with NLI_SHADOW=1 and its runtime, SYS-197 E4/E5.

## 2026-11-03: SYS-197 validity (ADR-025)
- Owner chose: Claude pre-labels the 200-row sample, the owner labels a blind 40, agreement gate >= 36/40.
- Built: `scripts/experiments/score_nli_handcheck.py` (build-blind / score; exit 0/1/2), `tests/unit/test_score_nli_handcheck.py` (6). Mutants: owner-wins swap, gate `<=`, blank-as-compared: 3/3 KILLED (the third after adding an assertion).
- Data: `handcheck_claude.csv` (200 labels, every `n` with a code + reason), `handcheck_owner_blind.csv` (40, seed 20261103, empty).
- Claude result: end 40/40, schedule 39/40, hedge 34/40, cause 34/40, denial 34/40. Failure modes in EXPERIMENTS.md 2026-11-03.
- Deviation from ADR-025's first draft: the borderline family is kept and flagged instead of the owner reading its other rows (that would have been about 96 rows).
- SYS-198 live check: still 0 `nli_shadow` rows. The only edition since go-live (10-26) built 0 arcs (SumoPod APIConnectionError at 12:05). Then the machine was off until 11-03.
- Noted, not filed: `_write_edition` evaluates `nli_shadow.default_scorer(...)` inside the edition's try block, and that block's except deletes the edition file. Today `HfScorer.__init__` cannot raise, so it is safe. Keep scorer construction trivial, or move it inside `record()`.

## 2026-11-04: ADR-026/027
- The owner could not judge y/n. Gemini became the blind labeller: `scripts/experiments/label_nli_gemini.py` (resumes after a 429; refuses replies whose ids do not match), 7 tests.
- Scorer reworked to two checks (`checks()`: label/garbled/copy -> label_ok n; type/cue/multi -> label_ok y, type_ok n). Precedence: owner ruling > agreement > Claude alone; an unresolved row is excluded. `--final` writes `handcheck_final.csv`. Exit 0/1/2/3. 14 tests; 5/5 mutants killed (codes swapped, rulings ignored, unresolved counted, type_ok dropped, missing-ruling exit).
- Owner rulings: `tests/fixtures/nli_eval/handcheck_owner_rulings.csv` (3 rows, with the question asked and the answer).

## 2026-11-04 (afternoon): SYS-198 live, SYS-197 type-misfit filter
- SYS-198: the 12:00 edition (for 11-03) wrote 20 `nli_shadow` rows, 20/20 scored, 19 with no gate tag. 124.5 s were added: lazy load plus 20 sentences plus the insert, with the budget clock started before the load. Posted on #428 and labelled ready-for-qa. Budget note: with 4+ arcs, later sentences get no verdict.
- Built `scripts/experiments/filter_nli_pairs.py`, with two rules:
  - denial-no-act: `gen_nli_pairs.DENIAL_ACT`;
  - cause-effect-side: word-token diff, links only in the edit's clause, plus *timbul/berasal/bersumber dari* as backward links. An added link or an added purpose clause is a cause edit.
  - Output: `tests/fixtures/nli_eval/pairs.jsonl`, with misfits as `error_type: other`, `declared_type` and `misfit` kept, LF.
- Hand check: 8 of 9 misfits caught, 0 judged fit flagged. Full set: 142 to `other` (denial 92, cause 50).
- Rejected: a multi-edit rule (3/12 precision).
- `gen_nli_pairs.py`: a denial seed now needs DENIAL_ACT, and the cause prompt says "the part that says why, not the result". The 2,974 existing pairs were not regenerated: the filter covers them.
- `tests/unit/test_filter_nli_pairs.py`: 23 tests, 10/10 hand mutants killed. Unit suite 4037 passed / 5 skipped.
- Deviation: SYS-197's natural set (spec 4.3, E3) was never built, because SYS-196's gold sample does not exist. Filed SYS-200 #430 to build it from live `nli_shadow` rows after about 10 editions, labelled with the ADR-026/027 method.
- SYS-199 arm A (2026-11-04): zero-shot on pairs.jsonl, 277 s on CPU. Held-out recall 0.9 at <= 3% false flags on cause, denial, end and schedule. Hedge misses dropped noun hedges ('perkara dugaan korupsi'); at tau 0.95 it flags 36% of restatements. Scores are not committed; they regenerate in 5 min.
