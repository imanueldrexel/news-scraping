# ADR-026: The blind second labeller of the NLI pair sample is Gemini, not the owner

**Status:** Accepted (owner, 2026-11-04)
**Date:** 2026-11-04
**Feature:** nli-faithfulness (SYS-197 #427)
**Author:** 10x-Team (QA + Architect)
**Supersedes:** ADR-025 decision 2 (the owner labels the blind 40). ADR-025's rubric, its agreement gate (>= 36/40)
and its family gates stay.

## Context
ADR-025 had the owner label 40 rows blind as a check on Claude's labels. The owner could not judge y/n: the rubric
asks two things at once, in NLI terms ("is the intended label right" and "does the edit test its type").

## Decision
gemini-2.5-flash labels the same seeded 40 rows (`handcheck_owner_blind.csv`, seed 20261103) blind. It gets the
ADR-025 rubric and never sees Claude's labels. There are 10 rows per call, so 4 calls of the free tier's 20/day.
Script: `scripts/experiments/label_nli_gemini.py`, output `tests/fixtures/nli_eval/handcheck_gemini_blind.csv`. It is
scored with `score_nli_handcheck.py score --second <that file>`:
- at >= 36/40 agreement, Claude's 200 labels stand;
- below that, the disagreements are reported to the owner as plain sentence pairs before anything else is decided.
On the 40 rows, Gemini's label is used where the two disagree, as the owner's would have been.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| One plain question per row for the owner ("Does B say anything A does not?") | A native reader checks the label part | Owner time; it checks only half the rubric | Owner chose Gemini |
| Accept Claude's labels alone | No cost | Nothing tests Claude's blind spots | Weaker than a second family |
| Gemini labels all 200 | No sampling | 20 calls is the whole day's free quota (the 22:30 drift audit shares it) | 40 is enough to measure agreement |

## Consequences
### Positive
- No owner time is needed. Three families are involved: DeepSeek wrote the pairs, Claude and Gemini labelled them.

### Negative
- No native human reader checks the labels. Two LLMs can share a blind spot (for example, reading *dugaan* the same wrong way), and agreement cannot see it.
- SYS-199 must say that validity comes from two LLM labellers, not a human.

### Risks
- Gemini's 429 (per-minute or per-day quota): the script stops and keeps the rows it already has. A re-run labels only the missing rows.
