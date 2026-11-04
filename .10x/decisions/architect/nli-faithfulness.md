# Architect: nli-faithfulness
Spec: `.10x/specs/2026-10-25-nli-faithfulness-design.md`. ADR-024.
- `core/nli_check.py` (pure scoring, lazy model) -> shadow writer -> `nli_shadow` table. Called after the lexicon gate, inside a try that cannot reach the edition.
- Sentence-level pairs, best entailing quote; hypothesis = gate's minimal proposition, else whole sentence.
- Failure modes: model load/OOM, timeout, slow 12:00 job, artefact leakage, encoder revision change. See spec section 6.

## 2026-11-04: arm B (ADR-028)
- Training is outside the app: `venv-train/` (GPU torch) -> `models/nli/<run>/` (save_pretrained + train_manifest.json) -> scored by `eval_nli.py --model <dir>` in `venv/` on CPU. Nothing in `newscrawler/` changes.
- Exam isolation: training pairs from articles with no exam seed (`gen_nli_pairs.py --exclude-pairs`); dev split by seed for early stopping; exam scored once.
- Loss: IndoNLI 3-class CE + our pairs BCE on softmax[entailment]; head and `p_entail` unchanged.

## 2026-11-05: arm B retry (ADR-029)
- New faithful kind `near_copy` (one meaning-preserving change); exam copy in a separate `near_copies.jsonl`, pairs.jsonl untouched.
- Training adds 1 near-copy + 1 identity pair per seed. Pass criteria fixed in ADR-029 before the run.
