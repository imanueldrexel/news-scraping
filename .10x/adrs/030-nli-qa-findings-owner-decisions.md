# ADR-030: Owner decisions on the SYS-197/198 QA findings -- whole-sentence hypothesis, natural set in SYS-200, leak gated by the wrong-premise control

**Status:** Accepted (owner, 2026-11-05: the three recommended options)
**Date:** 2026-11-05
**Feature:** nli-faithfulness (SYS-197 #427, SYS-198 #428, SYS-200 #430)
**Author:** 10x-Team (QA + Architect)
**Amends:** spec `2026-10-25-nli-faithfulness-design.md` 4.1 (hypothesis) and 4.3 (natural set, artefact rule); ADR-024's promotion rule is unchanged.

## Context
The 2026-11-05 QA audit failed SYS-197 and SYS-198 (#431-#439). Three findings needed the owner rather than a fix:
1. **#435**: the shadow scores the whole sentence for every claim, but spec 4.1 says to use the gate's minimal proposition when a gate fires. The SDE recorded this as a "v1 deviation", but the Done-when was never amended, and it still names that behaviour as a mutant to kill.
2. **SYS-197's natural set** was moved to SYS-200 by the dev, because the SYS-196 gold sample it was to share was never built.
3. **#431**: SYS-197 reported the hypothesis-only check at chance (0.43-0.54). That number comes from shuffled folds, which put each seed's near-identical pairs on both sides of the split. With seed-grouped folds the hypothesis alone predicts the label at cause 0.607, denial 0.801, end 0.712, hedge 0.671, schedule 0.743. Spec 4.3 says a family above about 0.6 is discarded or rewritten, so all five would go.

## Decision
1. **The shadow's hypothesis is the whole sentence, gated or not.** SYS-198's Done-when mutant item is withdrawn, and #435 is closed as not-a-defect. A proposition ticket is opened only if SYS-200 shows gate-tagged sentences scored worse than residual ones.
2. **The natural set belongs to SYS-200**, built from live `nli_shadow` rows. SYS-197 is judged on the targeted set only. **SYS-200 may not export until #436 (preview/replay overwrite a date's rows) and #437 (MAX_PREMISES cuts the alur quotes) are fixed and QA-closed.** Rows written before #437's fix are re-scored offline from `sentence` + `premise_ids`.
3. **The five families are kept.** The leak is measured honestly, and it is gated at the model, not at the set:
   - `eval_nli.hypothesis_only_accuracy` uses seed-grouped folds, and the reported numbers are the grouped ones (#431's fix, narrowed to this).
   - A per-type model claim on the targeted set (recall, false flags, tau) is valid only when that model's **wrong-premise AUC** (`compare_nli_arms.py`) is <= 0.65 for that type, i.e. the model needs the premise.
   - Promotion still requires the natural set (ADR-024), which has no generator and so no generator leak.

   Wrong-premise AUC measured by QA on 2026-11-05: see "Evidence" below.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| 1b. Build minimal propositions now | Spec as written | A new span extractor with its own bugs. Affects 1 of 33 live rows. Out of distribution for arm B v2 (trained on whole sentences) | Cost without a measured need |
| 1c. Store both verdicts | No information lost | Extra columns and runtime on a ~100-125 s budget | Same: no measured need |
| 2b. Keep the natural set in SYS-197 | Ticket as written | Its source (SYS-196's sample) does not exist; SYS-197 would stay open with nothing to do | SYS-200's source is better |
| 3b. Rewrite the families cue-balanced | A cleaner set | About $0.5, a new validity check with the owner's time, SYS-199 redone | The control already shows whether models read the premise |
| 3c. Discard families above 0.6 (spec 4.3) | Spec as written | Discards all five; SYS-199 has nothing to measure | Throws away a set the models demonstrably use the premise on |

## Consequences
### Positive
- SYS-197/198 can close on fixes that are already scoped (#432-#434, #436-#439, and #431 narrowed).
- SYS-199's arm A / arm B v2 results stand where the wrong-premise gate holds.
- SYS-200's source data is protected before it is exported.

### Negative
- The targeted set still carries generator cue words. Any new model must pass the wrong-premise control, and the held-out table alone proves nothing.
- Gate-tagged claims with an unrelated second clause can get a low p_entail from that clause.

### Risks
- A future model that learns the generator's style, as arm B v1 did, could pass the targeted table. Mitigation: the wrong-premise gate plus the identity/near-copy controls (ADR-029) are mandatory in `compare_nli_arms.py` runs.

## Dependencies
- #436 and #437 before SYS-200's export. #431's narrowed fix before SYS-197 can close.
- ADR-024 (promotion needs the natural set) is unchanged.

## Evidence
QA re-ran `compare_nli_arms.py` on 2026-11-05 over `pairs.jsonl` + `near_copies.jsonl` on CPU. The score caches are in the
session scratchpad and are not committed.

| type | arm A AUC | arm A AUC wrong premise | arm B v2 AUC | arm B v2 AUC wrong premise |
|---|---|---|---|---|
| cause | 0.99 | 0.57 | 1.00 | 0.57 |
| denial | 1.00 | 0.59 | 1.00 | 0.61 |
| end | 1.00 | 0.52 | 1.00 | 0.51 |
| hedge | 0.91 | 0.58 | 0.98 | 0.58 |
| schedule | 0.99 | 0.56 | 1.00 | 0.58 |
| other | 0.99 | 0.58 | 0.99 | 0.62 |

The gate (<= 0.65) holds for every type on both arms. With the right premise both arms separate faithful from unfaithful
almost perfectly; with another seed's premise they fall to 0.51-0.62. So their targeted-set numbers come from reading
the premise, not from the cue words a hypothesis-only classifier finds (0.61-0.80). The held-out recall,
false-flag and identity columns reproduce EXPERIMENTS.md 2026-11-04 / 2026-11-05 exactly.
