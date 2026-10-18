# ADR-020: A causal half is covered whole, names never cross the link, and the source's polarity and certainty carry over

**Status:** Accepted (owner, 2026-10-18: "Every word covered"; "Gate, exempt purpose"; "Any hedge word")
**Date:** 2026-10-18
**Feature:** newsletter-story-arcs (tracker #336); SYS-188 #389, SYS-181 #381 (send-back), SYS-189 #390, SYS-185 #385
(send-back), SYS-192 #393, SYS-183 #383 (send-back), SYS-187 #388, DBT-83 #395
**Author:** 10x-Team (Architect + Staff Engineer)
**Amends:** ADR-019 decision 3 (the 60% share per half), decision 5 (the anaphor allowance) and decision 6 (the
negators), and its implementation note "a NAME may stand anywhere in the link's sentence". Decisions 1, 2 and 4 stand.

## Context
QA's audit of ADR-019 (2026-10-18, `scripts/experiments/qa_2026_10_18/test_qa_1018.py`) kept six classes of false
causal claims. All six are the same flaw: the gate let the claim say something the link does not.
- **A swapped subject** (SYS-188): "Saham BBCA turun karena aksi jual asing" was backed by a BBRI quote, and "Harga
  cabai naik" by "Harga beras naik". 60% of a three-word half tolerates losing exactly the word that says WHAT.
- **A swapped place** (SYS-181): "Banjir di Solok memicu longsor di Padang" was backed by its reverse. A name could
  stand anywhere in the link's sentence, so it could stand on the link's OTHER side.
- **A borrowed sentence** (SYS-181): a side with its own subject and a "tersebut" took the whole previous sentence.
  That is the MK shape in two sentences.
- **Unlisted causal verbs** (SYS-189): didorong, dipengaruhi, seiring and membuat needed no quote. arcs-v5 prints four.
- **A dropped polarity** (SYS-185): "batal naik", "membantah ... naik karena" backed "naik karena".
- **A dropped certainty** (SYS-192): "diduga dipicu" backed "dipicu".
- **Lists** (SYS-183, SYS-187): "Karena A, B, dan C, Y" read A as causing B and C. "karena A, B, dan C" checked A only.

Measured on the stored replays (`scripts/experiments/sys188/missed_words.py`): the 12 backed claims' links miss only
verbs and adjectives (melebar, membahas, naik, deras, mengevakuasi), a time word (pertengahan), and three place names
that stand elsewhere in the link's sentence (Koto Tangah, Kuranji). No subject noun is ever missed.

## Decision
1. **Every word of a half is covered (owner, "Every word covered").** Every event word of the claim's half must be
   on the link's matching side, and so must its core clause's. `MIN_HALF_OVERLAP` is gone: a claim may drop words of
   the source, never add one. This is a deliberate trade. A true paraphrase ("hujan deras" for "hujan lebat",
   "melebar" for "peningkatan") is refused, and the retry writes the two facts apart.
   - The match is morphological, not semantic. `_root` also strips the ke-/pe-/per- ... -an circumfix ("kenaikan" ~
     "naik", "pelemahan" ~ "melemah"). That gives back true matches without tolerating a missing word.
   - Time-part words (awal, pertengahan, akhir) weigh nothing as facts, like months already do: the date guards hold
     times.
2. **Names never cross the link (SYS-181, SYS-188).** Every name of a half must be found: on the matching side, or
   elsewhere in the link's sentence, but **never on the link's opposite side**. v4 Padang's "Koto Tangah", which
   stands after the source's next causal word, keeps its room. A place swapped between the two halves does not.
3. **The previous sentence is lent only to a reference (SYS-181).** A source side takes the previous covered
   sentence when:
   - it is only a reference ("Hal ini", "Kondisi tersebut");
   - it has fewer than 2 content words;
   - its own subject (the content words that open it) ends in the anaphor and shares a word with the previous
     sentence ("Peningkatan proyeksi defisit tersebut" after "Defisit ... melebar").

   "Permohonan pemohon tersebut" after a sentence about MK lends nothing, and neither does "Longsor di desa tersebut",
   whose anaphor is not on its subject.
4. **The table holds the causal verbs of market copy (SYS-189, owner "Gate, exempt purpose").**
   - Backward: didorong, dipengaruhi, ditopang, berkat, seiring, dilatarbelakangi, bermula dari.
   - Forward: memengaruhi, mempengaruhi, menimbulkan, membuat, mendorong, menekan.
   - membuat, mendorong and menekan are causal words **unless a purpose word stands right before them** (untuk, guna,
     demi, agar, supaya, termasuk, ingin, berupaya). In the replays, all 5 "mendorong" are "untuk/termasuk mendorong
     X" (to promote), and all 4 "membuat" are causal.
   - menyusul and tertekan stay out: they are sequence and state words. The prompt lets "menyusul" link facts in time.
   - The prompt lists the same forms, and SYS-184's test pins the two together.
5. **Polarity carries over (SYS-185).**
   - batal, gagal, urung and tanpa are negators.
   - A denial frame earlier in the link's sentence (tidak benar, membantah, menepis, menampik, hoaks, keliru) negates
     the link itself, as "bukan karena" does. The claim must deny it too.
6. **Certainty carries over (SYS-192, owner "Any hedge word").** A hedge in the link's span (diduga, dugaan, menduga,
   kemungkinan, mungkin, apakah, ditengarai, disinyalir, indikasi) requires a hedge in the claim's span. Any hedge of
   the class will do. A claim may hedge what the source states flatly: that understates, it never invents.
7. **Lists (SYS-183, SYS-187).**
   - In a source, a fronted cause runs to the LAST clause boundary of its sentence part, and the effect is what
     follows it. "Karena A, B, dan C, Y": the cause is A, B and C, the effect is Y.
   - In the prose, the half on the side away from the sentence's start (the cause after a backward word, the effect
     after a forward word) runs over its comma-separated items up to a conjunction boundary. Each item must be
     covered.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Clause subject covered, 60% elsewhere | 0 of 12 replay claims lost | a swapped object or cause noun ("karena cuaca buruk" for "... banjir") keeps passing | owner chose every word |
| Names only | smallest change | cabai/beras, nikel/batu bara printed | QA's TestSubjectSwap stays red |
| Low-df words must be covered (QA's proposal) | targets the distinctive words | needs a corpus df table inside a pure gate; df drifts | a DB dependency in a check that must be deterministic |
| Gate every listed verb with no exemption | fully fail-closed | every "untuk mendorong kerja sama" costs a retry (5 per 39 arcs) | owner chose the exemption |
| Forbid ambiguous verbs in the prompt only | cheap | an ignored instruction prints unchecked | the class of SYS-184 |
| The same hedge word in the claim | strictest | refuses "diduga" written for "kemungkinan" | owner chose any hedge |

## Consequences
### Positive
- A claim can no longer say more than its link: no added word, no name from the other side, no dropped
  negation or hedge. Each rule is one line a mutant can break.
- The direction table covers the verbs the arcs actually write.

### Negative
- **More retries on true causes.** The replay recheck's backed count falls. The commit and SYS-188's comment report
  the exact before/after, and every lost claim. The owner accepted this with "Every word covered".
- A denial frame anywhere earlier in the sentence negates the link. "Kemenkeu membantah tudingan korupsi, dan harga
  naik karena X" denies nothing about the price, but it is read as a denial (fail closed: a retry).

### Risks
- Morphology: the circumfix rule can join two unrelated words that share a root ("pertanian" / "tani" is fine; a
  false join would only ever let a word count as covered). Its unit tests pin the stripped forms.
- The purpose exemption reads one word back: "untuk terus mendorong" is exempt only because "terus" is generic. A
  purpose clause written another way is gated (fail closed).

## Dependencies
- ADR-019's link model (one causal word, sides cut from the located source sentences) is unchanged.
- `story_words.content_words` decides names (capitalisation) and stop words.
- `story_arc.parse` wiring, refusal reason `sebab`, one retry and fallback: unchanged.
