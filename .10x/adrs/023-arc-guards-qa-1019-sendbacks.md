# ADR-023: The arc guards' 2026-10-19 send-backs -- an anaphor lends only what it names; word families, not forms

**Status:** Accepted (dev, 2026-10-20; QA rules on the send-back, two defects disputed)
**Date:** 2026-10-20
**Feature:** newsletter-story-arcs (tracker #336); SYS-181 #381, SYS-185 #385, SYS-189 #390, SYS-192 #393,
SYS-191 #392, SYS-193 #394, SYS-186 #387, SYS-177 #376; qa-defects #398-#407
**Author:** 10x-Team (SDE)
**Amends:** ADR-020 decision 3 (the anaphor allowance) and decision 5 (a denial *before* the causal word); the SYS-186,
SYS-191, SYS-193 and SYS-177 implementation notes in `source_check.py` / `story_arc.py`.

## Context
QA's held-out inputs (2026-10-19) broke each guard with the first unlisted form it tried, and found two structural
holes: an anaphor that shares one word with the previous sentence borrows all of it ("Penurunan saham BBRI tersebut"
after "IHSG turun"), and a fronted end ("Hingga 2026, pembekuan ...") is matched by its time alone.

## Decision
1. **An anaphor lends only what it names (#398).** The side's subject must share a word with the previous
   sentence, and every word after its head ("Peningkatan") must be there too. What it borrows is the parts of that
   sentence (cut at clause boundaries and "dan") that hold those words: "Penurunan saham BBRI tersebut" after
   "IHSG turun 1 persen dan saham BBRI turun 3 persen" borrows the BBRI clause only.
2. **A denial anywhere in the link's span denies it (#399)**, after the causal word too ("... dibantah maskapai"),
   as the hedge rule already reads. Denial words: + menyangkal / disangkal / sangkal(an) / penyangkalan (#400), and
   "ditepis" / "ditampik" (the old `(?:me|di)nepis` matched only "menepis").
3. **Hedges by verb with its active form (#402):** + diperkirakan / memperkirakan, dikira / mengira, diyakini /
   meyakini, disebut-sebut. Not the nouns "perkiraan" / "proyeksi": "Peningkatan proyeksi defisit tersebut" states
   a fact about a projection.
4. **Causal forms (#401):** + dipacu, terpacu, terdorong, buntut (backward). The prompt lists them.
5. **End openers (#403):** + diakhiri, berhenti, terhenti, dihentikan (pada). A **deadline** ("paling lambat",
   "selambat-lambatnya") is an end point in the prose; in a source it backs only a prose deadline, keeping SYS-186's
   "a source's paling lambat states no end".
6. **A fronted end's subject is the clause after its time (#404).** Only a clause with no content word on either
   side is matched by its time alone.
7. **A place after a verb of spread is no end (#406):** "meluas / menyebar / terasa ... hingga <Name> pada <time>".
   Both conditions are needed, so "berlaku hingga RUPS pada Juni 2027" and "hingga review indeks MSCI November 2026"
   are still read (fail closed).
8. **SYS-177's latar cue by plan root with its affixes (#407):** jadwal, target, rencana, janji, pasti, harap,
   kira, prediksi, proyeksi, agenda, upaya.

## Alternatives Considered
| Alternative | Why not |
|---|---|
| #407: every running latar span is a schedule unless a past word stands by it (QA's proposal) | `scripts` scan of the stored editions: the live 10-17 and 10-18 latars narrate "pada pertengahan Oktober" with no past word, and so does arcs-v5 10-08; QA's own control "Asap mulai meluas ke Jambi akhir Oktober" has none either. All four would be refused. |
| #405: a stated end must share two of the clause's nouns (one generic "saham" is not the subject) | Refuses the live MSCI source's true end: "Freeze MSCI berpotensi berlanjut hingga semester II-2027" shares only "berlanjut" with "Pembekuan berlanjut hingga semester II 2027" (two existing tests). DISPUTED on #405. |
| #401: gate "terimbas" | SYS-184's accepted `test_affected_is_no_link` pins "Sektor pariwisata terimbas pandemi." as no causal word. DISPUTED on #401 for QA to rule between the two. |
| #398: QA's "a name the anaphor's subject lacks is not covered" | Refuses the canonical SYS-181 case: "APBN" stands in the lent sentence, not in "Peningkatan proyeksi defisit tersebut". |

## Consequences
- Each new rule has a registry mutant (`sys181c_*`, `sys185c_*`, `sys189c_*`, `sys191c_*`, `sys192c_*`,
  `sys193c_*`, `sys186c_*`, `sys177c_*`).
- The lists still end somewhere: a cue, hedge or causal verb outside every family passes. Each family addition
  fails closed (more refusals, never fewer).
- `test_source_check.py::TestSys193EndSubject::test_a_clause_with_no_subject_is_matched_by_its_time` asserted the
  fallback #404 removes; it is replaced by `test_a_fronted_end_is_matched_by_the_clause_after_its_time` and
  `..._on_either_side_...`.
