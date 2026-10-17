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

## QA audit of the arc-guard rework (2026-10-15)
Report: `.10x/reviews/2026-10-15-qa-report.md`. QA tests and mutants: `scripts/experiments/qa_2026_10_15/`.

**Verdicts:**
- **Closed:** SYS-157, SYS-158, SYS-162, SYS-163, DBT-77.
- **Sent back:** SYS-164. A "sejak <bulan>" frame is counted as an anchor and an opening, so the tie refuses "Sejak September, ...". That frame was tied before 3e8b90c.

**Filed:** SYS-165 #361 (an agenda repeat in relative future time, BPGMN 10-12) and DBT-78 #362 (5 survivors of the dev's suites).

**Decisions:**
- SYS-163 drops a repeated agenda rather than refusing it: accepted.
- SYS-158 leans to collective after me-/di-/ber-: accepted. 0 bare-verb collectives in 297 real headlines.
- Compound counts, "kemarin lusa", "setengah bulan lalu" and kuartal-with-year records are not ticketed: 0-4 occurrences in 127,559 articles.
- QA's 10-14 fixture was wrong; fixed.

**Lesson:** a dev's "not mine, your fixture" can be right. Re-run the red test's refusal detail before arguing.

## 2026-10-16: the owner's read of arcs-v5 closes SYS-154
- Owner: "generally the v5 is much more fluid and better compared to previous one."
- They could not tell that a back-story spans several dates. When asked, they chose to keep it invisible (no span marker, no "Latar" label, no more dates).
- SYS-154 #349 closed. SYS-150's per-day blind preference (≥ 4/5) is still to be recorded. The read was v5 against earlier replays, not arcs against no arcs.

## QA audit of SYS-164 rework, SYS-165, SYS-166, DBT-78, SYS-161 (2026-10-16)
Report: `.10x/reviews/2026-10-16-qa-report.md`. QA tests and mutants: `scripts/experiments/qa_2026_10_16/`.

**Verdicts:** all five closed: SYS-164 #359, SYS-165 #361, SYS-166 #363, DBT-78 #362, SYS-161 #356.

**Filed:**
- SYS-167 #364 (P3): a modifier before "pekan lalu" hides it from the opening and frame rules.
- SYS-168 #365 (P3): `_FUTURE` misses "akhir tahun ini", "mendatang", "esok".
- SYS-169 #366 (P2): an agenda's relative future time is unchecked against the sources.
- SYS-170 #367 (P2): the change guard reads only "menjadi".
- DBT-79 #368: 4 survivors.
- DBT-80 #369: 27 stale registry mutants.

**Decisions:**
- SYS-161's Done-when "the re-run shows the Polri arc refused" is met by the offline check against all 24 stored Polri articles, because the v6 replay did not build that arc.
- The dev's calls are accepted: a future time in the latar counts as told; "akhir pekan ini" ≠ "pekan ini"; "pekan ini" schedules an agenda (bounded by SYS-169 once fixed).
- Not ticketed, since 0 occurrences in the replays and the prompt says "sejak": "semenjak" / "mulai" as frame words, and "berlaku per <date>" as a running period.

**Lesson:** a guard keyed on one wording ("menjadi", "pekan depan") is evaded by the next most common one. Before closing, count the wording's siblings in the corpus.

## QA audit of SYS-167..170, DBT-79, DBT-80 (2026-10-16 evening)
Report: `.10x/reviews/2026-10-16-qa-report-evening.md`. QA tests and mutants: `scripts/experiments/qa_2026_10_16_eve/`.

**Verdicts:**
- Closed: SYS-167 #364, SYS-168 #365, SYS-170 #367, DBT-79 #368, DBT-80 #369.
- Sent back: SYS-169 #366.

**Filed:**
- SYS-171 #370 (P2): no weekday future time ("Kamis depan") in `_FUTURE`.
- SYS-172 #371 (P3): change-claim forms "ke N", "hingga mencapai N", "menjadi total N", "<verb>, menjadi N".
- SYS-173 #372 (P3): awal/akhir pekan lalu span the whole week.

**Decisions:**
- **Rejected:** the dev's call that a future phrase inside a `_RELATIVE` phrase is judged by its span only. "akhir bulan ini" holds today from the 21st, so span backing (which the ticket chose against) creeps back in for 11 days a month.
- **Rejected:** "akhir/awal pekan lalu keep the whole week". Filed P3, not a send-back, since SYS-167's Done-when holds and no replay has one.
- **Accepted:** the OPS-32/33 retarget onto `_post` only. QA's 4 mutants on the other two copies are KILLED, so the redaction is guarded everywhere.
- Weekday future times are a missing table row (SYS-168's class), filed apart from the SYS-169 send-back.

**Lesson:** when a dev exempts one case from a new check because "another check judges it", test the other check on the days where its rule differs. Here, a span check is not a statement check whenever today is inside the span.

## QA audit of SYS-169 rework, SYS-171..173 (2026-10-16 night)
Report: `.10x/reviews/2026-10-16-qa-report-night.md`. QA tests and mutants: `scripts/experiments/qa_2026_10_16_night/`.

**Verdicts:**
- Closed: SYS-169 #366, SYS-172 #371, SYS-173 #372.
- Sent back: SYS-171 #370.

**Filed:**
- SYS-174 #373 (P2): a part of the current month ("akhir bulan", "akhir Oktober", "pertengahan bulan ini") is backed by today while its span runs.
- SYS-175 #374 (P3): "<verb> mencapai N" is no change claim.
- SYS-176 #375 (P3): "Hingga Senin (12/10)" is no running period, so a true claim is refused.

**Decisions:**
- **Rejected:** "a weekday never meets pekan depan". "Kamis pekan depan" reads only as "pekan depan", so SYS-171 is sent back rather than ticketed apart: the ticket's symptom, in another word order.
- **Accepted:** the Sunday call. A bare "Minggu depan" is next week in any case; only "hari Minggu depan" is the Sunday. Title-case headlines make the capital M meaningless, and the reader cannot tell them apart either.
- **Accepted:** "ke depan" windows count (owner).
- SYS-169 is closed although SYS-174 prints the same kind of false schedule. Its Done-when holds, and the new hole has another root cause: today backing a running span, outside `_FUTURE`.
- A bare weekday ("dijadwalkan Kamis.") is not filed: every weekday in the v4-v6 arcs carries its date.

**Lesson:** when a fix moves a phrase from one check to another, test the phrase's neighbours that stayed behind. "akhir bulan ini" moved to the key check, and "akhir bulan" did not.

## QA audit of SYS-171 rework, SYS-174..176 (2026-10-16 late)
Report: `.10x/reviews/2026-10-16-qa-report-late.md`. QA tests, mutants and probes: `scripts/experiments/qa_2026_10_16_late/`.

**Verdicts:**
- Closed: SYS-171 #370, SYS-175 #374, SYS-176 #375.
- Sent back: SYS-174 #373 (a span ending today counts as ended, so today backs an invented agenda "akhir bulan" on the 30th/31st, and likewise on the 20th and 10th).

**Filed:**
- SYS-177 #376 (P2): outside the agenda, a past date a source states backs a running span (~25-35% of arcs by corpus count).
- SYS-178 #377 (P2): bare "akhir tahun" / "akhir pekan" are read by neither table.
- SYS-179 #378 (P3): "awal/pertengahan X depan" is keyed as "X depan".

**Decisions:**
- **Accepted:** the dev's key call. "Kamis pekan depan" stays apart from "Kamis depan" (a retry both ways). A stated weekday of a week implies its week, one way only.
- **Accepted:** SYS-174 judged by field, not by "only a day ahead" everywhere. The dev measured 6/39 true replay arcs refused by the strict rule, and QA confirmed all 6 are latar past narration.
- **Rejected:** "The agenda is closed". It is open on each span's last day.
- **Rejected:** "the residual is the latar". It is the hari_ini and sekilas too, and it is not rare. It is filed apart (SYS-177), not as a send-back, because QA's own SYS-174 proposal allowed a source date to back the span. The new rule (by field, with a future verb before the phrase) is a design call with its own evidence.
- **Not filed, by count:** comma "Kamis, pekan depan" (0), adverb + "mencapai" (10), "hingga <hari> malam (d/m" (22, false refusal only), `relative_name` "akhir Oktober" for a this-week item (true; the past verb carries the tense).

**Lesson:** when a fix removes one day from a backing set, measure what the rest of the set still backs on real articles. Test the boundary where the fix's "has it ended?" test flips.

## SYS-150 ship gate (2026-10-17)
- Owner's blind per-day preference on arcs-v5: arcs 5/5 (rule >= 4/5).
- QA's hand-check first pass, judged against the stored sources:
  - `same_thread` 40/43 (93%): the 3 misses are thematic backstory, 2 of them in one arc (RI-Mesir);
  - `attributed` 5/6: the MK arc joins two separate reasons into an invented causal link.
- **Decision:** SYS-152 moves to P0, as SYS-150's Done-when pre-agreed.
- **Design note:** its rule (b) (cause-clause overlap) passes the MK sentence, because the clause is copied from a source's effect side. The check must match the effect + cause pair.
- **Lesson:** check a proposed guard against the real failure it exists for before building it. The first real unattributed cause slips through the rule as written.
- **Owner override (2026-10-17 09:40):** `NEWSLETTER_ARCS=1` was set before SYS-152 and SYS-174/177/178/179 closed. QA recommended waiting. The mitigation is QA's per-edition source check, with a rollback recommendation on the first false fact.

## QA audit of SYS-152 (ADR-018 causal gate) and DBT-81 (2026-10-17)
Report: `.10x/reviews/2026-10-17-qa-report.md`. QA tests and mutants: `scripts/experiments/qa_2026_10_17/`.

**Verdicts:**
- Closed: DBT-81 #380.
- Sent back: SYS-152 #342.
  - The gate is direction-blind: "B karena A" backs "A karena B". The Done-when "sehingga checked with the halves swapped" is not built.
  - The replay acceptance and exact-match numbers are unmeasured.

**Filed:**
- SYS-181 #381 (P1): two links in one quote (two adjacent sentences, or two clauses) back the MK shape.
- SYS-182 #382 (P1): the sentence cap is counted on the quote, not the source, so "..." and dropped full stops span a whole article.
- SYS-183 #383 (P2): in "Karena X, Y" the effect is never checked.
- SYS-184 #384 (P1): affixed and synonym causal words need no quote.
- SYS-185 #385 (P2): a negated claim is backed by the quote that states the opposite.
- DBT-82 #386: 8 of QA's 17 mutants survive.

**Decisions:**
- **Accepted:** the dev's measured deviations from ADR-018: the core-clause rule, the 70-word cap, the modal words, and the clause boundaries without "dan". Each is evidenced in the replay log, and QA's held-out cases agree.
- **Rejected:** "the direction does not matter because both halves are measured against the same quote". That is exactly what lets a reversed cause through. QA's design note had asked for "each on its own side of the connective".
- **Not filed:** "berdampak (pada)" and "terdampak" as causal words. In the replays they mean "affected", not a link (SYS-184 records it). Also not filed: a numeric change inside a quote ("2,5" vs "25" normalise alike). The quote is never printed, and the number guard checks the prose.

**Lesson:** a Done-when test can pass without the behaviour it names. Mutate the behaviour itself: swap the halves of a correct sentence.
