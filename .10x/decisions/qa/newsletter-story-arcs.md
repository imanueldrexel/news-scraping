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

## QA audit of SYS-154..160 (2026-10-14, afternoon)
Report: `.10x/reviews/2026-10-14-qa-report.md`. QA tests: `scripts/experiments/qa_2026_10_14/`.

**Verdicts:**
- **Closed:** SYS-155, SYS-156, SYS-159, SYS-160.
- **Sent back:**
  - SYS-157: "tiga pekan lalu" is read as "pekan lalu", "dua bulan lalu" as "bulan lalu";
  - SYS-158: a one-word record key, "N kali berturut-turut" unread, collectives after verbs claimed.
- **Held:** SYS-154, for the owner's 3-way read.

**Gates:** reproduced exactly from QA's copies of `arcs/` and `arcs-v5/`.
- QA added a "time-led" count (calendar date or non-"sejak" relative phrase at the opening): baseline 43/65 → v5 8/51, so the gate holds when relative time counts.
- v5 latar with ≥ 3 time anchors: 3/17.

**Filed:** SYS-161 #356 (P2), SYS-162 #357, SYS-163 #358, SYS-164 #359, DBT-77 #360.

**Decisions:**
- The dev's three deviations are accepted:
  - style named in the same detail as numbers and dates;
  - opens-on-date rather than any "pada <date>" for the refusal;
  - the tie by word families, names included.
- Under SYS-154's prompt, a recap is told in relative time, so the date-opening test no longer separates a recap from a frame (SYS-164).
- "Kini ... bertambah menjadi N" is a comparison claim no guard reads. It is right for year-to-date totals and wrong for separate waves (SYS-161, P2: a false fact a reader meets).
- The owner's read goes ahead on `arcs-v5`. `NEWSLETTER_ARCS=1` waits on the SYS-157/158 rework and SYS-161.

**Lesson:** a QA suite with red tests at baseline "kills" every mutant under `-x`. Count a kill only on tests that pass unmutated.
