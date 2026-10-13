# Newsletter story arcs: QA (2026-10-14)

Tracker #336. Source: the owner's read of the SYS-150 replay (`digests/preview/arcs/`), plus research `.10x/reviews/2026-10-14-arc-writing-research.md`.

## Finding
The arcs pass every automatic gate:
- 19/20 built;
- ≤ 856 words;
- 6/6 coverage;
- clean PDFs.

But they **read like a date-by-date chronicle**:
- 69% of latar sentences are date-led;
- 13/19 latar hold ≥ 3 dates;
- process non-events are told ("dibahas", "disebut");
- nothing ties the past to today.

The automatic gates measured length, coverage and cost, not whether an arc reads as a story. That is the QA gap SYS-160 closes.

## Risk assessment
- **Production:** none. `NEWSLETTER_ARCS=0`; the 12:00 edition is today's.
- **Product:** shipping arcs that read worse than today's edition would undo the reason for the feature.
- **Trust:** the obvious fix (relative time, framing) removes the one form of time claim code can verify. **SYS-157 (relative time) and SYS-158 (ordinals) are therefore release-blocking companions of SYS-154**, not follow-ups.

## Tickets filed (issue-first, tracker #336)
| ID | # | Type | Change |
|---|---|---|---|
| SYS-154 | 349 | bug P2 | prompt: frame first, ≤ 2 turning points, relative time, no date per fact |
| SYS-155 | 350 | enhancement | narrative worked example |
| SYS-156 | 351 | enhancement | `style` refusal: > 2 dates, repeated "Pada <date>" or same openings |
| SYS-157 | 352 | enhancement | relative-time phrases checked against chosen items' dates |
| SYS-158 | 353 | enhancement | ordinal/series claims held to the timeline |
| SYS-159 | 354 | enhancement | latar's first sentence shares an event word with today |
| SYS-160 | 355 | enhancement | replay metrics for "reads as a story" + owner's `reads_as_story` column |

## Quality gates before the A/B re-runs
1. SYS-160 metrics on the new replay:
   - date-led latar sentences ≤ 25%;
   - ≤ 2 latar with ≥ 3 dates;
   - continuity ≥ 90%;
   - arcs accepted ≥ 90%.
2. Unit tests + mutants for SYS-156..159.
3. The owner's 3-way read (new arc / old arc / today's) on 10-11 and 10-12, then the 5-day blind A/B (≥ 4/5).
