# ADR-024: NLI faithfulness check runs in shadow before it gates anything

**Status:** Accepted
**Date:** 2026-10-25
**Feature:** nli-faithfulness
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
The arc fact gates route a sentence by closed word lists and miss the first unlisted synonym. The gate-lexicon spec (decision 7) excluded NLI because Indonesian NLI measures about 74% on IndoNLI's expert set and nothing is measured for invented causes or dropped hedges. The owner decided on 2026-10-25 to do NLI regardless of Indonesian accuracy, and to publish a write-up if the results are good.

## Decision
Add a local multilingual NLI checker that scores each arc sentence against its cited quotes, records the verdict in `nli_shadow`, and does not affect output. Per-error-type thresholds are chosen on a held-out targeted set plus a natural set. A type is promoted to a retry-once signal only at recall >= 0.9 on both. Hard refusal is a separate later decision. This supersedes decision 7 of the gate-lexicon spec; the lexicon gate stays.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Hard refusal gate now | immediate coverage | ~74% expected accuracy refuses faithful sentences; thresholds guessed | unmeasured |
| Soft retry signal from day one | some effect immediately | still no measured threshold; changes the edition | no data to justify |
| LLM judge (DeepSeek) as the checker | strong on English | non-deterministic verdicts, per-sentence cost, not replayable | kept as a comparison arm only |
| English checker (MiniCheck) on translated text | best English accuracy | translation can drop hedges and change dates, the cues being protected | unmeasured second error source |

## Consequences
### Positive
- Real Indonesian numbers per error type before any behaviour change.
- The eval set and harness are reusable for every later checker, and for the write-up.
### Negative
- No protection from NLI until promotion; extra compute in the 12:00 job.
### Risks
- Synthetic-edit artefacts inflate recall: hypothesis-only check and a natural set guard it.
- Model load or timeout hurts the edition: no-verdict path and a time budget.

## Dependencies
- Shares its gold sample with SYS-196 (#426).
- Supersedes decision 7 of `2026-10-21-gate-lexicon-design.md`.
