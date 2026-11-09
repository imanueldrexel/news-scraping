# ADR-013: The week window's articles lead only when they hold the question's subject

**Status:** Accepted 2026-10-12 (owner approved the design)
**Date:** 2026-10-12
**Feature:** qa-second-pass-fixes-2026-10-12 (SYS-138 #317, sent back by QA)
**Author:** 10x-Team (Architect + Staff Engineer)
**Supersedes:** ADR-012 decision 1, only its rule for what may lead ("passes the floor"). The 7-day window, the fill, the reader-filter precedence and decision 2 stand.

## Context
- ADR-012 put every this-week article that passes the relevance floor ahead of the unwindowed ranking.
- The floor is a tail filter: a semantic-only paragraph at 0.55 passes it without a single question word.
- On a thin week, such a paragraph became card 1. QA's held-out set, plus the dev's live probe the same afternoon, found:
  - Danantara: a Primbon piece;
  - Harvey Moeis: a Pemko Medan piece;
  - Pertamina: a TNI motor-listrik case;
  - Garuda: BSA DKI.
- The obvious gates fail the ticket's own cases:
  - a keyword-coverage threshold at 0.6 drops this week's KPK (0.57-0.61) and IHSG (0.55) cards;
  - a final-score margin cannot separate the Primbon piece (0.402) from the 5th Danantara card.

## Decision
1. A window hit **leads** only when it passes the floor **and** holds the question's subject:
   - one of `KeywordQuery.names` when the question has names;
   - otherwise one of its `anchors` (the rare words that select paragraphs, ADR-006).
2. The test is SQL over `to_tsvector('simple', text)`, the same tokenization as `chunks.fts_vector` and `_coverage`.
   - It runs only for the window's semantic-only hits that pass the floor.
   - A keyword-retrieved hit holds the subject by construction (the FTS rule demands a name, or `need` anchors).
3. With no keyword query (`kq is None`), there is no subject to test, and the floor alone decides, as in ADR-012.
4. Hits that fail the gate are not removed: they rank in the unwindowed list.
5. Only gated hits count toward a full week. When at least `RAG_TOP_K` are gated, the second retrieval is skipped.
6. If the subject test fails (a DB error), the gate is closed: the window leads with keyword-retrieved hits only, and a warning is logged. An unchecked paragraph must not lead.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Coverage ≥ `RAG_MIN_KEYWORD_COVERAGE` (QA's first suggestion) | One existing number, no new SQL | KPK window cards 0.57-0.61, IHSG 0.55 | Breaks the ticket's Done-when (KPK/IHSG ≥ 3/5 this week) |
| Final score within δ of the unwindowed top `RAG_TOP_K` | No new SQL | Primbon 0.402 vs Danantara cards 0.45-0.41 | Cannot separate the reported case at any useful δ |
| Revert the window (ADR-007 weights only) | Simplest | KPK 0/5 this week again | Re-opens SYS-138's original defect |
| The full FTS admission rule (`need` anchors + a name) | Same rule as the keyword half | IHSG cards hold `ihsg` but not `kinerja` (`need` = 2) | Too strict for a lead test |

## Consequences
### Positive
- A this-week paragraph leads only if it is about what was asked. Off-topic fresh paragraphs fall back into the normal ranking.
- Nothing changes for questions without a week cue.

### Negative
- One extra round trip on the window path, for at most `RAG_FILTERED_K` short texts.
- A paragraph that names the subject only by a synonym ("BUMN holding" for Danantara) cannot lead. It still ranks normally.

### Risks
- A question whose "name" is a generic capitalised word ("Bank" in "Bank Indonesia") gates on it. Mitigation: names are only anchors, i.e. words with df < `NAME_DF`. Measured on the 10 held-out questions plus the replay (EXPERIMENTS.md 2026-10-12).

## Dependencies
- ADR-006 (anchors, names, the `simple` tokenizer), ADR-012 decisions 1 (minus its lead rule) and 2.
