# ADR-016: Story arcs are an in-edition stage over NEWS_L1, confirmed by the model and checked by code; no thread store

**Status:** Accepted 2026-10-13 (owner approved the design; tracker #336, SYS-147..152 = #337..#342). **Amended by ADR-017:** NEWS_L1 is loaded explicitly by the newsletter's own composition root (DBT-74), not inherited from `init_crawler()`; guards and the LLM loop come from `source_check`/`llm_json`.
**Date:** 2026-10-13
**Feature:** newsletter-story-arcs (`.10x/decisions/architect/newsletter-story-arcs.md`, PM `.10x/decisions/product-manager/newsletter-story-arcs.md`)
**Author:** 10x-Team (PM + Principal Architect)

## Context
The owner finds the 5-minute edition "too pointy" and single-day. They chose:
- 3-4 top stories told as pure-prose arcs over ≤ 30 days;
- a stated-only look-ahead;
- a blind A/B gate;
- replacement behind a switch.

The probe (EXPERIMENTS.md 2026-10-13) found:
- NEWS_L1 vectors locate a real thread for 4/6 leads, and correctly find none for the new one;
- KB entities fail on concept stories and drift;
- no cosine floor separates "same thread" from "similar topic".

The 12:00 job already holds NEWS_L1 and today's L1 vectors in memory.

## Decision
1. **Where:** a stage inside `newsletter_edition.build`, after the editor picks the top 3-4 stories. It runs only when `NEWSLETTER_ARCS=1`, together with the editor's 3-4-pick rules. With 0, the editor rules and the output are byte-identical to today's.
2. **Retrieval:** `core/thread_finder.py`:
   - searches NEWS_L1 with the centroid of the story's `terkait` L1 vectors;
   - keeps the window `[date-30, date)` above a wide floor (0.70);
   - keeps one item per day, at most 12 days, always including the earliest day;
   - reads headlines and dates from the DB;
   - is pure, with `search`/`lookup` injected.
3. **Membership:** the model chooses the `alur` items from the timeline (as `terkait` today). Code then checks each chosen item against today's subject (`story_words`): refuse on the first answer, demote on the retry.
4. **Writing and guards:** `core/story_arc.py`, one call + one retry. Every number, and every date written in the prose, must come from today's `terkait` texts or the chosen `alur` items. An `agenda` without a sourced date or event is dropped. A refused story falls back to its existing summary rendered as prose.
5. **No thread store.** The edition records `_edition.stories` (judul, terkait ids, alur ids) in the existing `newsletter_digests.categories` JSON. That is P1 story memory's input, with no migration.
6. **Entities are not used in P0.** They return after the #315 merge, as a second membership signal.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Precomputed `story_threads` table built nightly | Native story memory; reusable by a web thread page | Migration, a new job, thread merge/split maintenance; a wrong link persists and repeats | P1 is not decided as a store; a one-way door before the A/B shows arcs are wanted |
| Entity-mention retrieval (KB) | Explains "who"; already extracted | 3/6 leads return nothing; drift via generic places; duplicate entities until #315 | Probe result |
| LLM-written search query + keyword/vector hybrid | Better recall on concept stories | +1 call per story; nondeterministic; harder to replay | Vectors suffice for 4/6; revisit if arc precision < 90% |
| A fixed cosine floor without model confirmation | No extra reasoning | 0.70 drifts, 0.80 loses real history | Probe result |
| A model-written timeline/Kronologi with dates | Skimmable | The owner chose pure prose; model-written dates are a fabrication risk | The date guard covers prose dates instead |

## Consequences
- **Positive:**
  - two small pure modules;
  - no schema change;
  - reversible by one flag;
  - replayable without peeking;
  - cost under $0.01/day.
- **Negative:**
  - concept stories get thin arcs (they fall to the "why it matters" paragraph);
  - a long-running story repeats its back-story on consecutive days until P1;
  - the editor's rules change (3-4 picks, ≥ 1 non-finance).
- **Risks:**
  - invented causality: a prompt rule in P0, measured in the hand-check, a code check in P1;
  - the ship gate depends on the owner's time for 5 blind pairs.
- **Review trigger:**
  - arc precision < 90%, or repetition > 30% in the replay;
  - the owner wants a thread page in Tanya Berita: reconsider the thread store.
