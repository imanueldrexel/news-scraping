# QA report 2026-10-16 (night): SYS-169 rework, SYS-171, SYS-172, SYS-173

**Scope:** dev commit 1eff4b1 (HEAD 98bb7c0).

**QA's own tests:** `scripts/experiments/qa_2026_10_16_night/test_qa_1016_night.py`, written from the ticket texts with inputs the dev's tests do not use. It has 140 tests: 123 pass and 17 fail. Each failure is ticketed below.

**QA's mutants:** `scripts/experiments/qa_2026_10_16_night/qa_mutants_1016_night.py` (18), run in an archive copy of HEAD, never the live tree.

## Verdicts

| ticket | verdict | why |
|---|---|---|
| SYS-169 #366 | **closed** | QA's 32 pass. "akhir bulan ini" is refused on days 21-31 in 4 fields and named once. "akhir tahun ini" is refused in late December. Past phrases are still span-judged. Registry and QA mutants KILLED. The same hole through other month parts is ticketed apart (SYS-174). |
| SYS-171 #370 | **sent back** | "Kamis pekan depan" reads as "pekan depan" alone, so an invented weekday next week is printed (4 cases). QA mutant `qa16n_day_ahead_case_sensitive` survives the dev suites. Everything else holds, including the Sunday call. |
| SYS-172 #371 | **closed** | QA's 12 pass: more forms, no false claims, backed cases, end-to-end `number`. Registry and QA mutants KILLED. 18 replay claims, no new refusal. Two neighbours ticketed (SYS-175, SYS-176). |
| SYS-173 #372 | **closed** | QA's 25 pass: spans from Mon/Wed/Sun digests, boundary days in and out, end-to-end Sunday vs Tuesday item. 6 QA boundary mutants and the registry KILLED. Metrics byte-identical. |

## Baseline (all reproduce the dev's numbers)
- Unit: 3,453 passed, 5 skipped.
- QA files 10-14 / 10-15 / 10-16 / 10-16 evening: 267 passed.
- Registry `sys169_ sys170_ sys171_ sys172_ sys173_ qa16e_`: 29/29 KILLED by the four arc suites (`run_registry_mutants_in_copy.py`).
- QA mutants: 17/18 KILLED by the four arc suites. The survivor is killed by QA's file (30 failed vs 17 at baseline).
- `recheck_replays.py --db`: 39 arcs, 5 future times, 18 change claims. Each new "ke N" claim is backed.
- `--metrics-from` on copies of v4/v5/v6: `style_metrics.json` byte-identical.

## Findings
1. **SYS-171 send-back.** `_DAY_AHEAD` needs "depan" right after the weekday. With "Kamis pekan depan", `_FUTURE` matches only "pekan depan", so a source's "pekan depan" (or "Selasa pekan depan") backs an invented Thursday. The corpus has 51 articles with `<hari> pekan/minggu depan`. The dev's comment says the reverse ("a weekday never meets pekan depan").
   - Survivor `qa16n_day_ahead_case_sensitive`: no dev test keys a capitalised weekday ahead.
2. **SYS-174 #373 (P2), new.** The SYS-169 hole outside `_FUTURE`. A part of the current month ("akhir bulan", "akhir Oktober", "pertengahan bulan ini") is a `_RELATIVE` span, and today is in `days`. So an invented schedule is printed while its span runs: from the 21st for akhir, from the 11th to the 20th for pertengahan.
   - Corpus: 267 / 90 / 33 future-verb uses, mostly of other months.
   - QA's view: it blocks `NEWSLETTER_ARCS` like SYS-169 did.
3. **SYS-175 #374 (P3), new.** "<verb> mencapai N" with no to-word (43 articles) is no change claim. The dev noticed it on #371 and did not file it.
4. **SYS-176 #375 (P3), new.** `_TOTAL_OR_CHANGE` misses a running period dated by weekday, "Hingga Senin (12/10)" (2,096 articles). A true claim is refused: a false refusal only, but SYS-172 sends more claims to it.

## Noticed, not filed
- A bare weekday with no suffix ("dijadwalkan Kamis.", "Kamis ini") is never checked: neither past, future nor a date. The corpus has 357 articles with `<hari> ini`.
  - Every weekday in the v4-v6 arcs carries its date ("Kamis (8/10)"), as the prompt's format asks.
  - With no output evidence, QA leaves it. File it if a replay shows one.
- The dev's two notes on #370: a capital "Minggu lalu" read as the Sunday costs at most a retry. QA agrees; not filed.

## Recommendation
Keep `NEWSLETTER_ARCS=0` until SYS-171 and SYS-174 close. Both print a false schedule that no check catches.
