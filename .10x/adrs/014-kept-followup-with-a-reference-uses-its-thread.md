# ADR-014: A follow-up the rewrite keeps unchanged, but that refers back, is retrieved with its thread

**Status:** Accepted 2026-10-12 (owner approved the design)
**Date:** 2026-10-12
**Feature:** qa-second-pass-fixes-2026-10-12 (SYS-145 #328; depends on SYS-144 #327)
**Author:** 10x-Team (Architect + Staff Engineer)
**Supersedes:** ADR-010 decision 4, only for a `kept` rewrite of a follow-up that `refers_back`. Every other ADR-010 decision stands.

## Context
- ADR-010 searches a rewrite equal to the follow-up (`kept`) on the follow-up alone.
- The model keeps "Bagaimana dampaknya ke rupiah?" after "Apa keputusan The Fed terbaru?". It reads "rupiah" as the subject, although *dampaknya* points at the Fed decision.
- Alone, the follow-up gets 0/5 Fed cards. The deterministic fallback (own words + thread) gets 5/5.

## Decision
1. In `followup.resolve`, a `kept` rewrite of a follow-up for which `refers_back` is true is retrieved as the fallback thread is: own words + the newest previous questions, keyword terms per question (SYS-140), recency cue from its own words.
2. It is logged `rewrite=kept-thread`. The call is counted as before.
3. `refers_back` must not fire on *-nya* adverbs (SYS-144), or a real topic switch kept by the model ("Apa yang sebenarnya terjadi pada Garuda?") would be pulled back to the old thread.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Sharpen the prompt (resolve every *-nya* even when an object is named) | Fixes it at the source | Non-deterministic, costs a re-measurement of every set at each prompt change, and it fails silently on a key outage | The rule is free, testable and covers the same shape |
| Both: prompt and rule | Belt and braces | Two moving parts for one pair | YAGNI: revisit if a measured pair needs it |
| Leave `kept` alone | No change | Fed pair 0/5 | Fails SYS-145's Done-when |

## Consequences
### Positive
- An *-nya* follow-up with its own object keeps the thread's subject, whichever path ran.
- The rewrite and the fallback now agree on that shape.

### Negative
- A follow-up with a real *-nya* reference that truly changes subject, and that the model keeps, is pulled toward the thread. No such pair is known in the dev's or QA's sets; it is measured on them.

## Dependencies
- ADR-010, SYS-144's adverb list.
