# ADR-025: Validity of the LLM-written NLI pairs: a second model family pre-labels, the owner spot-checks blind

**Status:** Accepted (owner, 2026-11-03)
**Date:** 2026-11-03
**Feature:** nli-faithfulness (SYS-197 #427)
**Author:** 10x-Team (QA + Architect)
**Amends:** ADR-024 / spec 2026-10-25 section "Targeted pairs" ("hand-verified on a stratified sample"). Nothing else in ADR-024 changes.

## Context
SYS-197's targeted pairs (2,974) were written by deepseek-v4-flash on 2026-10-25. The spec drops any error-type family
whose stratified sample is under 81% valid. The sample is `tests/fixtures/nli_eval/handcheck_sheet.csv`: 200 rows,
40 per type (20 corrupted / 10 restated / 10 hard positive). It sat unlabelled for 9 days. The owner's labelling time
is the bottleneck, and SYS-199 waits on it.

## Decision
1. **Pre-label:** Claude (Anthropic, a different model family from the DeepSeek generator) labels all 200 rows against
   the rubric below and writes a reason for every `n`. Output: `tests/fixtures/nli_eval/handcheck_claude.csv`.
2. **Blind spot-check:** the owner labels a seeded random 40 rows (8 per type), without seeing Claude's labels.
   Sheet: `tests/fixtures/nli_eval/handcheck_owner_blind.csv`.
3. **Agreement gate:** `scripts/experiments/score_nli_handcheck.py` compares the two sets. If the owner and Claude agree on
   >= 36/40 (90%), Claude's labels stand for the 160 rows the owner did not see. On those 40 rows the owner's label wins.
   Below 36/40, the owner labels the remaining 160 (the original spec).
4. **Borderline family:** a family at 81% to 87% passes the spec's gate, but at n=40 its interval still reaches below
   81%. It is kept, and SYS-199 reports its numbers with that flag. A family under 81% is dropped, as the spec says. Before SYS-199 measures it, the failure
   modes the reason codes name are filtered out of the full pair set where a rule can find them, for example a
   denial seed with no denial verb. (First draft: the owner reads the family's other rows. That was dropped when the
   pre-label put three families at 85%, which would have meant about 96 more owner rows.)

### Rubric (one label per row)
- `y` when **both** hold:
  - the `intended` label is right: `supported` means the premise alone entails the hypothesis, and `unsupported` means it does not;
  - the pair tests its type:
    - a corrupted row changes one thing, and that thing is of the declared type (cause / hedge / denial / end / schedule);
    - a hard positive keeps the type's cue word(s);
    - a restatement only needs entailment.
- `n` otherwise. The note gives the reason code: `label` (the intended label is wrong), `type` (an edit of another
  kind, or of a word that is not the cue), `multi` (more than one change), `cue` (the premise has no instance of the
  type, so the test is empty), `copy` (verbatim or trivial), `garbled` (the hypothesis has no clear meaning).
- Two edits of the same type (two hedges dropped) are still `y`. `multi` is for a second change of another kind.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Owner labels all 200 (spec) | Fully independent | ~1-1.5 h owner time; it has not happened in 9 days | The fallback if agreement < 90% |
| Gemini as the second labeller | A third family, scriptable | Free tier 20 req/day (OPS-20); it spends quota; no human in the loop | Same circularity as Claude, without a human check |
| Skip validity, trust the generator | Zero cost | The 10-25 entry already saw an invalid `sehingga` cause row; per-type numbers in SYS-199 would be unfounded | Spec forbids publishing unverified pairs |

## Consequences
### Positive
- SYS-199 is unblocked after about 20 minutes of owner time.
- Every `n` has a written reason, so the pair generator can be fixed per failure kind.

### Negative
- Labels from two LLMs can share blind spots, for example both reading an Indonesian hedge the same wrong way. The blind 40 measure this but cannot remove it.
- With 8 rows per type in the spot check, the per-type agreement is only indicative. The gate is on the 40 rows overall.

### Risks
- Claude is lenient on near-synonym edits ("katanya" -> "ujarnya" labelled as a valid hedge corruption). Mitigation: the reason codes, plus the owner's blind rows, which oversample nothing and so see the base rate.

## Dependencies
- Constrains SYS-199: report which labeller decided each family's validity.
