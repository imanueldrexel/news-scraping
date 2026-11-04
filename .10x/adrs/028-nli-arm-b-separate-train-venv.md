# ADR-028: Arm B fine-tune trains in its own venv, on pairs from articles the exam never saw

**Status:** Accepted (owner, 2026-11-04)
**Date:** 2026-11-04
**Feature:** nli-faithfulness (SYS-199 #429)
**Author:** 10x-Team (Architect + Senior Engineer)
**Builds on:** ADR-024 (shadow first), spec 2026-10-25 section 4.5 (arm B). Does not change the production path.

## Context
Arm A (zero-shot mDeBERTa XNLI) reaches recall 0.9 at <= 3% false flags on cause, denial, end and schedule, but hedge
needs tau 0.95 and then wrongly flags 36% of restatements: the model reads a dropped noun hedge ("perkara dugaan
korupsi" -> "perkara korupsi") as the same meaning. The owner chose arm B over arm C on 2026-11-04: a fine-tuned local
model is a one-off cost and can become the production check; a DeepSeek judge (arm C) is comparison-only by the
10-25 decision and would charge per sentence.

Constraints:
- The 2,974 pairs in `tests/fixtures/nli_eval/pairs.jsonl` are the exam. Training on them, or on other pairs from
  the same 712 articles, makes the A-to-B gain meaningless.
- Training needs the GPU (RTX 3060 Laptop, 6 GB, driver 527.99 = CUDA 12.0). The app venv has torch 2.8.0+cpu and
  runs the 07:00/12:00/19:00 jobs; a broken torch install there breaks them.

## Decision
1. **Separate venv** `venv-train/` (gitignored) holds torch 2.8.0+cu126 and the same transformers / tokenizers /
   safetensors / sentencepiece / protobuf pins as `requirements.txt`; its freeze is `requirements-train.txt`. `venv/`
   and `requirements.txt` are not touched. The weights are saved with `save_pretrained` and scored in `venv/` on CPU
   by the existing `eval_nli.py --model <dir>`, which also proves the production venv can load them.
2. **Training pairs** come from a new `gen_nli_pairs.py` run on 1,000 seeds per type (about 20k pairs) drawn only
   from articles that hold no exam seed (`--exclude-pairs pairs.jsonl`). Hard cap $2 (estimate $0.75). Stored LF in
   `data/nli_train/train_pairs.jsonl` and committed: they cost money and are the weights' only reproducible input.
3. **General NLI** against forgetting: IndoNLI train (Mahendra et al. 2021, CC BY-SA 4.0, about 10k pairs), 3-class
   cross-entropy. Our pairs are binary (faithful / unfaithful), so their loss is binary cross-entropy on the softmax's
   entailment probability: the head stays 3-class and `p_entail` keeps its meaning for the scorer and the shadow table.
4. **Model selection without the exam:** 5% of the training seeds (by seed, not by pair) are a dev split for early
   stopping. The exam is scored once, after training, with arm A's exact protocol (tau chosen on one half, measured
   on the other).
5. **Weights** go to `models/nli/<run-name>/` (gitignored), with `train_manifest.json` beside them: base model and
   revision, data sha256s, hyperparameters, seed, dev metrics, `model.safetensors` sha256. Wiring a fine-tuned model
   into `NLI_MODEL` is a later owner decision; the shadow keeps arm A.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| GPU torch in `venv/` | One venv; the 12:00 check could use the GPU | A bad install (old driver) breaks every scheduled job; requirements.txt churn | Owner chose the separate venv |
| Arm C (DeepSeek judge) | No training, likely strong on hedges | Per-sentence spend forever; non-deterministic; comparison-only by the 10-25 decision | Owner chose B as the cost-efficient path |
| Train on the existing 2,974 pairs (cross-validation) | No new spend | ~3k pairs is below the 10-30k the spec plans; folds share generator and articles with the exam | Too small and leaky |
| Binary head (replace the 3-class head) | Simpler loss | Loses neutral/contradiction; IndoNLI can't be used as is; scorer contract changes | The entail-only BCE keeps everything |

## Consequences
### Positive
- Production cannot be affected by the experiment; rollback is deleting `venv-train/` and `models/`.
- The exam stays clean: no article overlap, no tuning on it.

### Negative
- Two venvs to keep in step: the pins shared with `requirements.txt` must match, or a weight saved by one
  transformers version may load differently in the other. `requirements-train.txt` records them.
- About 3 GB download for the CUDA wheel, 1.1 GB per saved model.

### Risks
- Driver 527.99 is older than CUDA 12.6; the cu126 wheel relies on CUDA minor-version compatibility (driver >= 527.41
  on Windows). If `torch.cuda.is_available()` is False or a kernel fails, the owner updates the NVIDIA driver; CPU
  training is not a fallback (hours per epoch).
- Same generator for training and exam: the targeted-set gain is optimistic. SYS-200's natural set decides promotion.
- DeBERTa-v3 overflows in fp16; train in bf16 (Ampere supports it).

## Dependencies
- SumoPod balance for about $0.75 (owner approved, cap $2).
- Promotion of any type still needs SYS-200 and the owner's sign-off (ADR-024).
