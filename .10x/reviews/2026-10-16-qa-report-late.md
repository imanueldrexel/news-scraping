# QA report 2026-10-16 (late): SYS-171 rework, SYS-174, SYS-175, SYS-176

**Scope:** dev commit eeb205c (HEAD 5445c2e).

**QA's own tests:** `scripts/experiments/qa_2026_10_16_late/test_qa_1016_late.py`, written from the ticket texts and the dev's comments with inputs the dev's tests do not use. It has 179 tests: 152 pass, 27 fail. Every failure returns `kept` (the hole), never another refusal, and each is ticketed below.

**QA's mutants:** `scripts/experiments/qa_2026_10_16_late/qa_mutants_1016_late.py` (11), run in an LF archive copy of HEAD (`git -c core.autocrlf=false archive`), never the live tree.

**Probes (read-only):** `probe_running_span_backing.py`, `probe_forms_corpus.py` in the same folder.

## Verdicts

| ticket | verdict | why |
|---|---|---|
| SYS-171 #370 | **closed** | QA's 54 pass: every weekday incl. the Sunday x 4 week forms, synonyms/case, another weekday or week, the dev's key call both ways, the implied week one way only, every field, SYS-166/163 through the new key, "Kamis pekan lalu" untouched. Registry 14/14 and QA's 5 mutants KILLED. The comma form is in 0 articles. |
| SYS-174 #373 | **sent back** | Today no longer backs a span that runs past it (QA's 57 pass). But a span that **ends today** counts as ended, so today backs it. In the agenda an invented "akhir bulan" is then printed on the 30th/31st, "pertengahan bulan ini" on the 20th and "awal bulan" on the 10th: 3 days a month. The dev's comment says "The agenda is closed" (6 red). |
| SYS-175 #374 | **closed** | QA's 22 pass: every change verb adjacent to "mencapai", comma/case/spacing, words before N, no false claim (no verb, a noun, the gap case, dates), source backing, end-to-end `number`. Mutants KILLED. Residual by count: an adverb between the verb and "mencapai" (10 articles). |
| SYS-176 #375 | **closed** | QA's 10 pass: the Sunday, "hari", comma, long date, "sejak", capitals; a bare weekday or no period word is not one; end-to-end kept. 6 mutants KILLED. Residual by count: a time of day before the date (22 of 2,155 articles; false refusal only). |

## Baseline (all reproduce the dev's numbers)
- Unit: 3,493 passed, 5 skipped.
- QA files 10-14 .. 10-16 night: 407/407.
- Registry `sys171_ sys174_ sys175_ sys176_ qa16n_`: 25/25 KILLED by the four arc suites.
- QA night mutants: 18/18 KILLED. Three showed NOT FOUND on a CRLF copy; all KILLED on an LF copy.
- QA late mutants: 11/11 KILLED by the dev suites (the span-end boundary, each piece of `_DAY_OF_WEEK`, the implied week, the words after "mencapai", each piece of `_WEEKDAY_BEFORE_DATE`).
- `recheck_replays.py --db`: 39 arcs, 5 future times, 18 change claims, 6 running spans with 0 refused.

## Findings
1. **SYS-174 send-back.** `_backing_days` returns `known` when `last <= digest_date`, so today backs a span ending today. A plain `<` would also stop today backing "sejak Oktober", which `_since_month` clips to today. The dev must tell a part from a start. QA test: `TestSys174LastDayOfTheSpan` (6 red, 2 green guards).
2. **SYS-177 #376 (P2), new.** Outside the agenda, a past known day inside a running span still backs it. `parse` counts every date that today's `terkait` articles state.
   - On 26/10 a source's "Minggu (25/10)" backs an invented "Aturan barunya terbit akhir bulan." in the hari_ini, sekilas or latar. "akhir bulan ini" in the same sentence is refused.
   - Corpus: 13.4% of articles posted 22-30/9 state a past date inside "akhir September" in their guard text. That is about 25% of 2-article and 35% of 3-article arcs, before counting alur items.
   - The dev's comment names the residual as the latar only.
   - All 6 replay running spans are latar past narration with no future verb before the phrase. So "hari_ini/sekilas/judul as agenda" plus "a future verb within 4 words before -> agenda" costs 0 on the replays.
   - QA test: `TestRunningSpanPastSourceDate` (8 red, 1 green guard: the replay's "akan" after the phrase).
3. **SYS-178 #377 (P2), new.** Bare "akhir tahun" / "akhir pekan" are read by neither `_FUTURE` (it needs ini/depan/mendatang) nor `_RELATIVE`. An invented one is printed in any field.
   - Corpus: 141 / 21 articles with a future verb before the bare form.
   - Latent: no replay arc writes one. Two CNBC headlines carry "di Awal Pekan" / "Jelang Akhir Pekan".
   - QA test: `TestBareYearAndWeekEnd` (9 red, 3 green).
4. **SYS-179 #378 (P3), new.** `_FUTURE` reads only "akhir" as a part. "awal / pertengahan pekan|bulan|tahun depan" is keyed as the whole period, so an article's "pekan depan" backs an invented "awal pekan depan" (55 articles write the form). QA test: `TestNarrowedFuturePart` (4 red, 3 green).

## Considered, not filed
- **The comma form "Kamis, pekan depan"** (the dev's residual): 0 articles.
- **An adverb before "mencapai"** (SYS-175): 10 articles; "<verb> N% mencapai N": 5. True claims, so only a one-event source makes them false.
- **A time of day before the date** (SYS-176): 22 articles. A false refusal only.
- **`relative_name` names a this-week item "akhir Oktober"** (the dev's note). On 29/10 the label "akhir Oktober" for 27/10 is true, and the sentence's past verb carries the tense. That is style, not a false fact.

## Release readiness
`NEWSLETTER_ARCS` stays 0. SYS-174's agenda boundary and SYS-177 both print a false schedule. SYS-177 hits about a quarter to a third of arcs late in each month part.
