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
