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

## 2026-11-04: SYS-199 arm B plan (ADR-028; owner approved separate venv + ~$0.75, cap $2)
- B1 `gen_nli_pairs.py`: `--exclude-pairs` (skip exam articles) + `--workers` (concurrent calls; 5,000 sequential calls would take hours). Unit tests. No spend.
- B2 generate 1,000 seeds/type -> `data/nli_train/train_pairs.jsonl` (LF), cap $2. SPEND (approved).
- B3 `venv-train/` with torch 2.8.0+cu126 + app pins; `requirements-train.txt`; check `torch.cuda.is_available()` (driver 527.99 risk -> owner driver update).
- B4 `scripts/experiments/train_nli_armb.py`: IndoNLI + our pairs, seed-split dev, bf16, manifest. Unit tests for the pure parts (data mixing, split, loss) in `venv/`.
- B5 train; B6 score the exam on CPU, arm A protocol, A vs B table + hyp-only on the training pairs.
- B7 EXPERIMENTS.md entry, #429 comment (not ready-for-qa: verdict waits for SYS-200), state files.
- Order: B1 -> B2 (runs in background) || B3 -> B4 -> B5 -> B6 -> B7.
