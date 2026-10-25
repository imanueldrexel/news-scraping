# EM: nli-faithfulness plan (2026-10-25)
Tasks <= half a day each. SYS-198 and SYS-197 are independent; SYS-199 needs both.

## SYS-198 (#428) shadow
- T1 migration `migrate_nli_shadow.sql` + table model + register in `scripts/migrate.py`; apply to `newsaggregator_test` (prod after owner backup/approval).
- T2 `core/nli_check.py`: scorer interface (`Scorer` protocol, stub for tests), HF scorer lazy-loaded, `NliVerdict`, no-verdict on failure.
- T3 `core/nli_shadow.py`: arc -> sentences (per field) -> premise quotes (terkait guard_text + alur item_source) -> rows; best entailing quote; time budget; writer.
- T4 wire after the edition is written in the generator, inside try; env flag `NLI_SHADOW` (default 0 until live check).
- T5 tests: unit (stub scorer), mutants, integration (rows written, output byte-identical).
- T6 pick the checkpoint (verify current multilingual XNLI models) and measure runtime on one real edition.

## SYS-197 (#427) eval
- E1 harness `scripts/experiments/eval_nli.py` + 10-pair golden fixture (stub model) -- offline, no spend.
- E2 hypothesis-only baseline (TF-IDF + LR) in the same script.
- E3 natural-set extractor from past arcs/QA defects (no spend).
- E4 pair generator (LLM) -- SPENDS MONEY; run only after owner confirms the budget (SumoPod balance was ~$0 on 10-15).
- E5 stratified hand-check sheet for the owner (OWNER TIME).

## Order
T1, T2 -> T3 -> T4 -> T5 -> T6; E1, E2, E3 in parallel with SYS-198; E4/E5 gated on the owner.
## Risks
Owner labelling time; SumoPod balance; checkpoint download size/licence; the 12:00 job runtime.
