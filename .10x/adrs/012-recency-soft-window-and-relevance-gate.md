# ADR-012: "This week" questions prefer the last 7 days (a soft window); "now / today" freshness counts only for an article about the question

**Status:** Proposed 2026-10-12. The shape was owner-chosen; the numbers are filled in from the measurement, then this becomes Accepted.
**Date:** 2026-10-12
**Feature:** qa-senior-fixes-2026-10-12 (SYS-138 #317, SYS-112 #289)
**Supersedes:** ADR-007 decision 3's weights for the week cue and its recency gate. Its cue table and the keyword half's newest-first rule stay.

## Context
- **SYS-138.** "pekan ini / minggu ini" from the search box (no date filter) gets 2-10-week-old articles. A weight of 0.2 with a 3-day horizon gives a 4-day-old article only 0.064 over a 24-day-old one, less than a small semantic gap. The week's articles exist (141 KPK, 359 IHSG).
- **SYS-112.** After SYS-109's 80-word windows, "Siapa Menteri Keuangan sekarang?" leads with same-day Danantara stories that only mention the minister. They clear the 0.55 recency gate, get the 0.3 "sekarang" weight, and outrank the cabinet story (semantic 0.776 vs 0.645).
- The two pull in opposite directions, so they are tuned on one measurement.

## Decision (shape)
1. **Soft window for the week cue.** A "pekan ini / minggu ini / sepekan terakhir" question without a date filter:
   - is retrieved first with a 7-day window (`from_day = today - 6`, the same path as the `rentang` filter: FTS SQL filter, FAISS over-fetch then filter);
   - when that yields at least `RAG_TOP_K` hits over the floor, those are the result;
   - otherwise the window's hits come first and the unwindowed ranking fills the rest.
   - A reader's own date filter overrides the window.
2. **Relevance gate for freshness.** Under any cue, recency counts only for an article whose semantic score is at least the floor **and** within `RECENCY_GATE_DELTA` of the best candidate's semantic score. "About the question", relative to what the corpus offers, not a fixed cosine.
3. **The numbers** (the window's days, `RECENCY_GATE_DELTA`, any weight change) are chosen offline on the replay set plus QA's SYS-138 questions asked unfiltered, then recorded here.

## Alternatives Considered
| Alternative | Why not |
|---|---|
| Larger week weight only | QA's arithmetic: to lift a 4-day-old article over a 0.1-closer 24-day-old one the weight must be ≥ 0.5, which puts any same-week mention above the BI decision (ADR-007's measured failure) |
| Hard 7-day filter | A quiet topic would return nothing for "minggu ini" |
| Gate on keyword coverage | The Danantara stories had coverage 1.0: coverage can't tell a mention from the subject |

## Consequences
- **Positive:** "this week" means this week when the week has answers; a passing mention can't ride the freshness bonus.
- **Negative:** a second retrieval pass for week-cue questions whose window is thin (+~100-600 ms).
- **Risk:** the delta is a corpus-relative judgment, tuned on ~20 questions. The probe's questions are the regression set.
