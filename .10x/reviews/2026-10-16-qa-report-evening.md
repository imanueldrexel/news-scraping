# QA report 2026-10-16 (evening): SYS-167..170, DBT-79, DBT-80

**Scope:** dev commits ee1b6cd (SYS-167..170, DBT-79) and 7712d4f (DBT-80), HEAD 7712d4f.
**QA's own tests:** `scripts/experiments/qa_2026_10_16_eve/test_qa_1016_eve.py`, written from the ticket texts with inputs the dev's tests do not use. 68 tests: 54 pass and 14 fail, each failure ticketed below.
**QA's mutants:** `scripts/experiments/qa_2026_10_16_eve/qa_mutants_1016_eve.py`, run in archive copies of HEAD, never the live tree.

## Verdicts

| ticket | verdict | why |
|---|---|---|
| SYS-167 #364 | **closed** | QA's 7 pass. 3 dev mutants and 2 QA mutants KILLED. Exact weekday from Mon/Wed/Sun digests. Metrics reproduce. |
| SYS-168 #365 | **closed** | QA's 8 pass. 8 dev mutants and 4 QA mutants KILLED. Keys in caps and with spacing; past narrations excluded. |
| SYS-169 #366 | **sent back** | The judgement call fails: an unstated "akhir bulan ini" is printed on days 21-31 (span backing by today). A mutant survives: latar/judul/sekilas are unguarded. |
| SYS-170 #367 | **closed** | QA's 2 pass. 5 dev mutants and 2 QA mutants KILLED. Date shapes; end-to-end `number` refusal. Held-out forms ticketed apart. |
| DBT-79 #368 | **closed** | All 4 survivors KILLED by the four arc suites alone. |
| DBT-80 #369 | **closed** | 25/25 retargets KILLED by `tests/unit`. The hygiene test goes red on QA's own refactor. 0 stale. Retargets faithful on spot check. |

## Baseline
- Unit: 3,421 passed, 5 skipped.
- QA files: 10-14 84/84; 10-15 + 10-16 115/115.
- Arc registry for this batch: 26/26 KILLED by the four arc suites.
- `recheck_replays.py --db` reproduces the dev's numbers: 39 arcs, 5 future times, change claims 8 -> 10, 1 newly refused (v4 Padang "pekan ini").
- `--metrics-from` on copies of v4/v5/v6 reproduces:
  - v4: time-led 10/48, >= 3 anchors 4/16, tied 16/16;
  - v5: 11/51, 1/17, 17/17;
  - v6: 1/12, 1/4, 4/4.

## Findings
1. **SYS-169 send-back.** "akhir bulan ini" is a future time (SYS-168) and also a `_RELATIVE` phrase. The dev left it to the span check, which backs a phrase whose days hold today. So from the 21st an invented one always passes, against the ticket's own "no span backing". Digest 12/10 refuses it; 21/10, 26/10 and 31/10 print it (agenda and latar).
   - Mutant `qa16e_future_latar_unchecked` (check only agenda + hari_ini) survives the dev suites.
2. **SYS-171 #370 (P2), filed.** `_FUTURE` has no weekday. An unstated "Kamis depan" / "Senin mendatang" / "hari Jumat mendatang" agenda is printed, while "besok" is refused. About 200 articles write `<hari> depan/mendatang`, against 348 for "minggu depan".
3. **SYS-172 #371 (P3), filed.** The change guard misses four forms on a one-event total:
   - "ke N" (425 articles; the replays write "naik ke 3,28%");
   - "hingga mencapai N" (145);
   - "menjadi total N";
   - "<verb>, menjadi N" (both in SYS-170's own table).

   Mutant `qa16e_change_no_posisi` survives.
4. **SYS-173 #372 (P3), filed.** The dev's call: "awal/pertengahan/akhir pekan lalu" span the whole week, so a Sunday item backs "awal pekan lalu". A month's parts are narrowed; a week's are not. Corpus 398 articles; 0 in the replays.

## Mutation summary
| set | result |
|---|---|
| dev arc registry (`sys167..170`, DBT-79's 4, 2 retargets) | 26/26 KILLED (arc suites) |
| QA arc mutants (`qa16e_*`) | 10/12 KILLED by dev suites; the 2 survivors are KILLED by QA's file -> SYS-169 send-back, SYS-172 |
| QA Telegram redaction in `_post_document` / `_post_html` (the 2 copies DBT-80's retarget leaves out) | 4/4 KILLED (`tests/unit`) |
| DBT-80 retargets | 25/25 KILLED (`tests/unit -x`) |

## Not ticketed (counted)
- A year or clock time after "hingga" is read as the change figure. 102 and 4 articles. It is refused only if no source sentence holding it has a change verb, so it costs a retry at worst.
- A line break inside a change claim hides it. This predates SYS-170: `_sentences` splits on newlines.
- A stated "akhir pekan depan" does not back an agenda's "pekan depan": a false refusal, and rare.
- The hygiene test's sibling checks need git and the doc files, so they fail in an archive copy. Not a defect: copy `EXPERIMENTS.md` in when mutating in a copy.

## Release readiness
`NEWSLETTER_ARCS` should stay 0 until SYS-169 (sent back) and SYS-171 (P2) are fixed. Both print a false schedule in a top story. SYS-172/173 (P3) do not block. The owner's SYS-150 blind A/B and the SumoPod top-up are unchanged.
