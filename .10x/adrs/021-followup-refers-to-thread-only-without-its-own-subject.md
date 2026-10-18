# ADR-021: A follow-up goes to its thread only when it names no subject of its own; a possessive -nya is its root

**Status:** Accepted (owner, 2026-10-19: "Anaphor gate + list"; SYS-146 "Separate ticket" for the off-subject ranking)
**Date:** 2026-10-19
**Feature:** qa-1013-queue (SYS-144 #327 send-back, SYS-145 #328 send-back, SYS-146 #331)
**Author:** 10x-Team (Architect + Staff Engineer)
**Amends:** ADR-014 decision 3 ("`refers_back` must not fire on -nya adverbs", which made the rule depend on a list's
completeness); ADR-006's `terms` (a possessive -nya word is matched by its root). ADR-014 decisions 1 and 2 stand.

## Context
- ADR-014 retrieves a `kept` follow-up that `refers_back` with its thread, and the fallback has always done so. Both
  paths ask one lexical question: does the follow-up hold a reference word (-nya, dia, mereka, tersebut) that is not
  on SYS-144's adverb list?
- QA (2026-10-13) showed that list is never complete. Six common adverbs (sebaiknya, sebetulnya, nantinya, sayangnya,
  secepatnya, sepenuhnya) pulled real topic switches to the old thread on the served path. Sritex fell from 4/5 to
  1/5, Waskita Karya from 5/5 to 2/5.
- Mining 20,000 articles (`scripts/experiments/sys144/mine_nya_adverbs.py`) confirms it cannot be completed from data
  either. The sentence-opener signal ranks back-pointing connectives (akibatnya 0.82, sebaliknya 0.77) above real
  adverbs. sebaiknya, secepatnya and sepenuhnya almost never open a sentence.
- ADR-014's accepted risk is real: a switch whose -nya points inside the follow-up ("Berapa utang Waskita Karya dan
  kapan jatuh temponya?") is pulled to the thread, 1/5 vs 5/5 alone.
- SYS-146: in the `simple` configuration, "pemimpinnya" is its own rare lexeme. It became the question's heaviest
  required anchor, so "Apa itu Danantara dan siapa pemimpinnya?" got fts=0 and 0/5.

## Decision
1. **A follow-up goes to its thread when it holds a reference word and names no subject of its own.** One predicate,
   `followup.refers_to_thread(question, previous)`. Both the `kept` path (ADR-014) and the fallback use it.
   - Its *own subject* is a name (`story_words.names`: an acronym, or capitalised where no sentence starts; never a
     month, a title or a digit token) that the thread's words do not hold (`story_words.vocabulary`).
   - **Object phrases:** a name inside an object phrase (ke, kepada, terhadap, bagi, untuk, pada, di, atas + up to 4
     words) is what the thread's event affects ("Bagaimana dampaknya ke IHSG?"). Such a name is not the follow-up's
     own subject...
   - ...**unless a reference word follows it.** An Indonesian -nya anaphor points backward, so "Apa yang terjadi pada
     Sritex dan bagaimana nasib karyawannya?" resolves *karyawannya* to Sritex.
2. **The adverb list stays, wider, as the first layer** (SYS-144). It keeps a follow-up that names nothing from being
   read as a reference ("Apa sebaiknya dilakukan?"). It holds QA's six held-out adverbs, plus those from the mined
   list whose question use has no referent. The list now lives in one module, `web/nya_words.py`, with the
   possessive rule below.
3. **A possessive -nya word is matched by its root** (SYS-146). In `keywords.terms`, a word ending in -nya that is
   not an adverb or a word that merely ends in -nya (hanya, punya, tanya…) stands as its root when the root keeps 3+
   letters ("pemimpinnya" → "pemimpin", "buyback-nya" → "buyback"). An adverb is no keyword at all. The
   possessive is the referent, not the subject. The root is what the paragraphs write.

## Alternatives Considered
| Alternative | Measured (on-topic cards, production, no model call) | Why not |
|---|---|---|
| Wider list only (QA option 1) | QA held-out adverbs fixed; the inner-reference switch stays 1/5 | The next unlisted adverb repeats the bug; the mining shows the list cannot be derived |
| Name gate, every new name | QA held-out B 27/35 (head 20); **object set 5/30** (head 25) | "dampaknya ke IHSG" loses the thread |
| Name gate minus object phrases | object 25/30; **held-out #2 8/30** (head 12) | "terjadi pada Sritex … pailitnya" loses its subject |
| **Decision 1** (+ backward anaphor) | B 27/35; object 25/30; held-out #1 33/40 (head 23); held-out #2 16/30 (head 12); dev/QA sets equal (±1 noise, SYS-194) | — |
| Sharpen the rewrite prompt (ADR-014's rejected option) | not measured | Non-deterministic, does nothing on the fallback, and costs a re-measure per prompt change |
| SYS-146: a -nya word is never an anchor (coverage only) | — | QA's Done-when needs "pemimpinnya" and "pemimpin" to build the same anchors |

## Consequences
### Positive
- The served path no longer depends on the adverb list being complete for a follow-up that names its own subject.
- ADR-014's accepted risk is closed: a switch with an inner reference stays alone (QA's 4 `stays_kept` cases turn
  green).
- One definition of "a -nya word" (`web/nya_words.py`) serves both the follow-up rule and the keyword terms.

### Negative
- **Accepted cost:** a name *before* the reference word that is not its antecedent ("Apa kata Garuda soal dampaknya?"
  after an avtur question) is read as the follow-up's own subject. The question is retrieved alone: 1/5 vs 5/5. Only
  the rewrite can tell the speaker from the antecedent, and it usually does.
- A lower-case subject is not a name ("bagaimana nasib karyawan sritex"), so it falls back to the list layer.

### Risks
- The object-phrase prepositions are a closed list chosen on 2 measured sets. A new preposition shape degrades to
  "its own subject", which is the conservative direction (the follow-up is retrieved on its own words).
- Root-stripping can widen a keyword ("harganya" → "harga", df higher), so the replay must be re-run
  (`probe_rag_rank_breakdown.py --replay`). A root that falls under the 3-letter minimum is kept as it was.

## Dependencies
- ADR-010/014 (follow-up rewrite and its kept path), ADR-006 (keyword terms), `story_words.names/vocabulary`.
- SYS-194 (#396): deterministic FTS order, so the before/after comparisons are not noise.
- SYS-195 (#397): the off-subject semantic ranking that SYS-146's Done-when also lists. It is not this ADR's change.
