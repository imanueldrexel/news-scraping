# Design: NLI faithfulness check for story-arc sentences, shadow first

**Date:** 2026-10-25
**Status:** approved in brainstorming (owner, 2026-10-25)
**Feature slug:** `nli-faithfulness`
**Evidence:**
- `research_notes/Indonesian NLI faithfulness checking/targeted_adaptation.md` (targeted errors, synthetic-error training, low-resource adaptation, thresholds, budget);
- `research_notes/Indonesian claim cue detection/faithfulness_checkers.md` and `reports/Indonesian claim cue detection.md` (checker accuracy, Indonesian support).

## 1. Problem
The arc fact gates (SYS-196, `2026-10-21-gate-lexicon-design.md`) route a sentence by hand-typed cue words. A claim whose cue is not listed is never checked, and closed word lists failed on the first unlisted synonym in every QA pass. The gate cannot flag what it never routes. An NLI check judges the sentence against its cited quotes without needing the cue, so it can cover the residual.

The owner decided on 2026-10-25 to do NLI **regardless of its accuracy on Indonesian**. This supersedes decision 7 of the gate-lexicon spec ("No NLI or LLM judge inside the gate"); the gate-lexicon work itself is unchanged.

## 2. What is known and not known
- Indonesian zero-shot (XNLI transfer, XLM-R large) scores 73.8 on IndoNLI's expert set, translate-train 75.7. XNLI has no Indonesian, so this is cross-lingual transfer.
- Weakest IndoNLI categories: dates 68-70, numbers 58-65, negation 72-79.
- Nothing is measured for invented causes, dropped hedges or invented schedules in any language. NLI models are biased toward "entailed" on high-overlap pairs (HANS), which is the profile of these errors.
- So the first deliverable is a measurement, not a gate.

## 3. Decisions (owner, 2026-10-25)
1. **Shadow first, then promote.** The NLI verdict does not change output in v1. A type is promoted to a retry signal only on measured recall.
2. **Eval set is a deliverable.** If the numbers hold, an Indonesian write-up follows (`reports/`). The set is not published without a further owner decision.
3. **LLM judge (DeepSeek) is a comparison arm only**, not the checker (non-deterministic, per-sentence cost against the ~$100 budget).

## 4. Components

### 4.1 `newscrawler/core/nli_check.py`
`check(premise_quotes, hypothesis) -> NliVerdict(p_entail, p_neutral, p_contradict, model_revision)`.
- Premise: the cited `terkait` quotes, **sentence level**, one pair per quote; the sentence's verdict is the best entailing quote.
- Hypothesis: the gate's minimal proposition ("X disebabkan oleh Y", "berlaku hingga D") when a gate fired; the whole sentence when none did (the residual).
- Model: a multilingual XNLI checkpoint (arm A). Local, CPU or the 6 GB GPU. Loaded lazily; a missing model or a timeout yields "no verdict", never an exception into the edition.

### 4.2 Shadow recording
Table `nli_shadow` (migration, registered in `scripts/migrate.py`): `id, edition_date, arc_id, sentence, error_tag, gate_decision, p_entail, p_neutral, p_contradict, model_revision, created_at`. Written after the lexicon gate decides, in the same run, in a `try` that cannot affect the edition. The 12:00 job gets a time budget for it.

### 4.3 Eval set (`tests/fixtures/nli_eval/`, generator in `scripts/experiments/`)
- **Targeted pairs:** about 200 human-verified atomic-edit pairs per error type (hedge dropped, cause invented, denial flipped, end date changed, schedule invented). Each corruption is paired with a faithful restatement, plus hard positives that keep the same cue words where the source supports them. Built from real project quotes by an LLM, then hand-verified on a stratified sample (discard a family below 81% validity).
- **Natural set:** about 200 real arc sentences (QA #413-#425 and past refused/passed sentences). Shares the gate-lexicon gold sample, so labelling is done once.
- **Artefact check:** a hypothesis-only classifier on every set; above about 60% on balanced pairs means the edits leak.

### 4.4 Evaluation harness (`scripts/experiments/eval_nli.py`)
Per error type: recall at a threshold, false-flag rate on hard positives, hypothesis-only accuracy, comparison with the lexicon gate alone. Thresholds are chosen per type on the eval set to hit the recall target, and re-checked when the generator model changes.

### 4.5 Fine-tune (arm B, only if arm A misses)
Start from the arm A checkpoint; train on 10-30k LLM-written contrastive pairs plus about 10k general NLI (IndoNLI train or translated MNLI) to prevent forgetting. 6 GB GPU, base size, max_len 256, fp16, gradient accumulation. Evaluate on the same held-out sets; the A to B gain per type is a reported result.

## 5. Promotion rule
A type moves from shadow to a retry-once signal when recall >= 0.9 on its targeted set at an acceptable false-flag rate on hard positives **and** the natural set confirms it. A hard refusal is a separate later decision. Not in this spec.

## 6. Failure modes
| Failure | Handling |
|---|---|
| Model fails to load / OOM | no verdict; one WARNING per run; edition unaffected |
| NLI slows the 12:00 job | per-run time budget; remaining sentences skipped and counted |
| Synthetic edits leak (hypothesis-only high) | discard or rewrite the family; report the number |
| LLM-written pairs are invalid | stratified hand check; drop family below 81% |
| Encoder revision changes | `model_revision` stored on every row; thresholds re-derived |
| Shadow rows pile up | retention of 90 days |

## 7. Testing
- Unit: verdict parsing, premise/hypothesis construction per gate type, no-verdict paths, shadow write cannot raise into the edition (mutants: swallow removed, hypothesis uses the whole sentence for a gated claim).
- Integration: `nli_shadow` migration applied to `newsaggregator_test`; a replayed edition writes rows and the output is byte-identical to a run without NLI.
- Eval harness: golden fixture of 10 pairs with a stub model gives known recall/false-flag numbers.

## 8. Out of scope
Changing the lexicon gate; promotion to a refusal; the DeepSeek judge as a production path; the web -nya lists; publishing the eval set.

## 9. Tickets
- SYS-197 (#427): eval set (targeted pairs, natural set, artefact check) and harness.
- SYS-198 (#428): `nli_check` + `nli_shadow` + shadow wiring in the arc run.
- SYS-199 (#429): arm A vs arm B vs LLM arm measurements and thresholds; arm B fine-tune if A misses; write-up if the numbers are worth publishing.
