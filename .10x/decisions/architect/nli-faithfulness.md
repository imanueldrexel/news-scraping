# Architect: nli-faithfulness
Spec: `.10x/specs/2026-10-25-nli-faithfulness-design.md`. ADR-024.
- `core/nli_check.py` (pure scoring, lazy model) -> shadow writer -> `nli_shadow` table. Called after the lexicon gate, inside a try that cannot reach the edition.
- Sentence-level pairs, best entailing quote; hypothesis = gate's minimal proposition, else whole sentence.
- Failure modes: model load/OOM, timeout, slow 12:00 job, artefact leakage, encoder revision change. See spec section 6.
