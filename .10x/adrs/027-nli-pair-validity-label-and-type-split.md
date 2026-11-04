# ADR-027: NLI pair validity is two checks: "label correct" (gated, agreed) and "fits its type" (buckets the pair)

**Status:** Accepted (owner, 2026-11-04)
**Date:** 2026-11-04
**Feature:** nli-faithfulness (SYS-197 #427)
**Author:** 10x-Team (QA + Architect)
**Supersedes:** ADR-025's single y/n rubric, and the dimension ADR-025/026's agreement gate is measured on. Gate
values (>= 36/40, family 81%, borderline to 87%) are unchanged.

## Context
Gemini's blind labels (ADR-026) agreed with Claude on 33/40, under the 36/40 gate. Of the 7 disagreements, only 3 were
about meaning (does B say something A does not?). The other 4 were about the rubric's second clause, "tests its type":
- does negating *keliru* / *dikaitkan* count as a denial test?
- does an edit to the object of *timbul dari* count as a cause?
- must a supported row keep its type's cue?
Those 4 are definitions, not readings. Agreement measured them as noise.

## Decision
1. Every pair carries two checks:
   - **label_ok**: the `intended` label is right (supported = the premise alone entails the hypothesis);
   - **type_ok**: the pair tests its declared type. It is judged only when label_ok is y.
   Old codes map as follows: `label` / `garbled` / `copy` -> label_ok n; `type` / `cue` / `multi` -> label_ok y, type_ok n.
2. **The gate is on label_ok:** Claude vs Gemini on the blind 40, >= 36/40. Result: **37/40, holds.**
3. **The owner rules on label_ok disagreements**, in plain language ("Does B say something A does not? Ya / Tidak / Ragu").
   File: `tests/fixtures/nli_eval/handcheck_owner_rulings.csv`. Precedence for a row: owner ruling > Claude and Gemini
   agreeing > Claude alone (the 160 rows Gemini did not see). A disagreement without a ruling is excluded.
   Owner, 2026-11-04: `cause-313943-67311a-3` y (Gemini right), `cause-239647-f7243c-2` n, `cause-276590-f6a6f0-0` n
   (Claude right).
4. **type_ok is Claude's judgement**, recorded with a reason. A pair with label_ok y and type_ok n is not dropped: it
   goes to an `other` bucket. It counts in the overall NLI score but not in its declared type's per-type number.
5. **Family gate:** the label_ok share per declared type, 81% to drop and 81-87% borderline, as before. type_ok rates
   are reported next to it. SYS-199 must filter type misfits from the full pair set before it reports per type.

Output for SYS-199: `tests/fixtures/nli_eval/handcheck_final.csv` (id, error_type, kind, intended, label_ok, type_ok,
decided_by).

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Keep one y/n; the owner sets a policy for each definition dispute | One number | Owner judgement on rubric questions, which the owner said they cannot make | That is the question that failed |
| Drop every disputed row | Simple | Throws away pairs whose label everyone agrees is right | Loses eval data for a bookkeeping reason |

## Consequences
### Positive
- The human only answers reading questions, and only on real disagreements (3 rows).
- Type misfits stay usable as general negation/paraphrase pairs.

### Negative
- type_ok has a single labeller (Claude).
- The `other` bucket's size in the full set is unknown until the seed filters run.

## Dependencies
- SYS-199 reads `handcheck_final.csv` and applies the seed filters to the 2,974 pairs.
