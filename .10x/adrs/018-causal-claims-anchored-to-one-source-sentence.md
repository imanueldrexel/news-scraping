# ADR-018: A story arc's causal claim must rest on one quoted source sentence, checked by code

**Status:** Accepted (owner, 2026-10-17: "better to follow that rather than we invented new approach, at least it's proven")
**Date:** 2026-10-17
**Feature:** newsletter-story-arcs (tracker #336), SYS-152 #342
**Author:** 10x-Team (Architect + Staff Engineer), from `reports/In prompt causal claim checking.md`

## Context
- Story arcs link events with causal words: *karena, akibat, lantaran, dipicu, memicu, sehingga, imbas, disebabkan, menyebabkan*.
- The prompt alone forbids an unsupported cause (`story_arc.PROMPT`), and no code checks it. SYS-150's hand-check of arcs-v5 found 1 of 6 causal sentences invented. The 10-09 MK arc says MK "tidak dapat mendiskualifikasinya karena permohonan tidak dapat diterima". The sources give two separate reasons: no legal standing, and "bukan ranah MK".
- Each half of that sentence is true and quotable, and only the link is invented. A check per half, or per atomic fact, passes it. So does SYS-152's original rule (b), which matches the cause clause alone. Rule (a), "attributed means exempt", passes it too ("MK menyatakan").
- Since 2026-10-17 arcs are live (`NEWSLETTER_ARCS=1`).
- Research summary (the report cites every source):
  - Same-pass self-checking does not reliably catch a model's own errors (Huang et al. ICLR 2024; Kamoi et al. 2024; CoVe joint vs factored).
  - A verbatim quote proves the words exist, not the relation: 83-93% of quotes match the source exactly, while only 37-79% of claims are supported by them (2026 studies).
  - LLM and small judges reach ~75-77% balanced accuracy on English grounding benchmarks, are weakest on link/discourse errors, and are unvalidated in Indonesian.
  - The established pattern is: quote produced with the claim, a mechanical check of the quote, then a support check (ALCE, RARR).

## Decision
Three layers, in the established pattern, anchored to one sentence:
1. **Prompt (the arc call).** A `"sebab"` list is the FIRST JSON field: `[{"artikel": n, "kutipan": "<one source sentence copied verbatim, holding the causal word, the effect and the cause>"}]`, at most 2 entries, `[]` if none. Every causal word in the prose must rest on one entry.
2. **Code gate (`story_arc.parse`, new refusal reason `"sebab"`). This decides.**
   - Find every causal word in judul / hari_ini / latar / agenda / sekilas.
   - The `kutipan` must be a normalised substring of source `n`: whitespace, quote marks and case unified, "..." may bridge within one source. Up to two adjacent sentences are allowed, for "Hal ini menyebabkan ...".
   - The `kutipan` must contain a causal word (equivalence classes: karena = lantaran = disebabkan oleh; ...).
   - Split the prose sentence at its causal word, swapping the halves for forward connectives (sehingga, menyebabkan, memicu). The effect half and the cause half must EACH share at least 60% of their content words (`story_words`) with that same `kutipan`.
   - Attribution never exempts a sentence.
   - On refusal: one retry ("drop the causal word or state the two facts separately"), then the existing fallback.
3. **Judge: shadow only, a separate ticket.** It runs on sentences the code passed, preferably on another model family (Gemini). It sees one sentence plus the full sources, never the arc or the `kutipan`. It gets an open question first, then a verdict. It logs only, for 2 weeks; a veto (remove, never rescue) only after QA confirms catches the code missed.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Prompt rule / in-prompt self-check only (status quo) | free, no code | already failed 1 in 6; self-check without external signal does not help (Huang et al.) | proven insufficient |
| SYS-152 as filed: attribution exempts (a); cause-clause overlap (b) | simple | passes the MK sentence on both rules | misses the observed failure |
| Separate LLM judge as the gate | handles paraphrase | ~75-77% accuracy, worst on link errors, unvalidated in Indonesian, judge biases | not reliable enough to decide; kept as a shadow |
| Strict code without a quote field (search the sources for a matching sentence) | no prompt change | must search all sources by fuzzy match; more false matches | the quote points code to the exact sentence; ALCE: in-generation citation beats post-hoc by 47% recall |

## Consequences
### Positive
- Deterministic, so it can be mutation-tested like the other arc guards.
- It catches exactly the observed failure (both halves true, link invented).
- It costs ~60-100 output tokens per causal arc plus an occasional retry: fractions of a cent a day.

### Negative
- It fails closed: a true but paraphrased cause whose source sentence lacks a causal word is refused (expected: Ojol of the six). The retry then drops the causal word, so some true "why" is lost to sequence wording.
- The evidence field at the front of the JSON adds a format constraint for a flash-class model. Watch arc acceptance after retry, which must stay >= 90%.

### Risks
- A quote may be paraphrased rather than verbatim (exact-match rates 41-93% across models); normalisation and the "..." bridge reduce this. Measure on the replays.
- A cause spanning two non-adjacent sentences is refused. Accepted.
- The thresholds (60%, two adjacent sentences) are untested on this corpus: tune them on the stored replays, never on the live edition.

## Dependencies
- `story_words` content-word definition; `story_arc.parse` retry/fallback; the replay harness (SYS-150) for measurement.
- The shadow judge (separate ticket) depends on a working second-provider key (Gemini).
- Supersedes SYS-152's original rules (a)/(b).
