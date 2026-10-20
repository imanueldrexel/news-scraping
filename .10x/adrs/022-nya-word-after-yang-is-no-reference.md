# ADR-022: An -nya word in an adverb's place is no reference; an object phrase runs to its clause's end

**Status:** Accepted (dev, 2026-10-20; QA rules on the send-back)
**Date:** 2026-10-20
**Feature:** qa-1019-sendbacks (SYS-144 #327 / SYS-145 #328 / SYS-146 #331; qa-defects #408 #409 #410 #411 #412)
**Author:** 10x-Team (SDE)
**Amends:** ADR-021 decision 1 (object phrases: "the preposition and up to 4 words") and decision 2 (the adverb
list). ADR-021's own-subject rule and its backward-anaphor rule stand.

## Context
QA (2026-10-19) found that ADR-021's object-phrase rule hands the decision back to the adverb list. When a
follow-up's only new name stands in an object phrase ("Apa yang aslinya terjadi pada Garuda Indonesia?"), the name
is masked, so an unlisted -nya adverb (harusnya, aslinya, mestinya, kayaknya) reads as a reference and the switch
goes to the old thread. Live: Garuda 3/5 and 5/5 -> 0/5. A name as the 5th word of an object phrase ("ke saham bank
BUMN seperti BBRI") read as the follow-up's own subject (#410).

## Decision
1. **An -nya word right after "yang" is no reference**, listed or not, unless it is a verb with its object clitic
   ("Siapa yang memimpinnya?"). In "Apa yang X-nya <verb>" the clause's subject is "apa", so the slot holds an
   adverb. `followup._references`, so `refers_back` and `refers_to_thread` agree.
2. **The object phrase runs to the end of its clause** (punctuation), not over a new question ("... ke IHSG dan apa
   kata analis ..."). No word cap.
3. **The adverb list grows by the spoken forms** that are rare enough to become keyword anchors: harusnya,
   mestinya, baiknya, benarnya, betulnya, patutnya (a listed se-...-nya adverb without se-), aslinya, kayaknya,
   keliatannya. `NOT_CLITIC` holds every affixed form of "tanya" (ditanya was cut to "dita"). Keywords stay
   list-based (ADR-021 decision 3): SYS-146's Done-when needs "pemimpinnya" to build the same anchors as "pemimpin".

## Alternatives Considered
Measured with `scripts/experiments/sys144/measure_object_adjacency.py` (production, read-only, no model call; both
columns on the 8cd85d6 adverb list, so they differ by the rule alone). `risk` and `switch_1020` were written before
the first run.

| Alternative | qa_1019 (QA's 4 switches) | switch_1020 | risk (thread refs, non-adjacent object) | object / held-out sets |
|---|---|---|---|---|
| ADR-021 (head) | 6/20 | 11/16 | 24/30 | 24/30, 33/40, 16/30 |
| Mask only the object phrase right after a reference word ("dampaknya ke X") | 17/19 | 16/16 | **1/30** | equal |
| **Decision 1 + 2** | 14/20 (17/19 with decision 3) | 16/16 | 24/30 | equal |

The adjacency rule loses "Kenapa harganya naik di Jakarta?", "Apa yang dia katakan tentang utang di DPR?" and four
more natural thread questions. Decision 1 keeps all of them.

## Consequences
### Positive
- QA's shape ("Apa yang <adverb>-nya <verb> ... pada <Name>?") no longer depends on the list.
- No measured pair is worse.

### Negative
- `story_words.is_verb` is a prefix heuristic: "mestinya" reads as a me- verb, so decision 1 misses it (the list
  catches it). A sentence-initial unlisted adverb ("Kayaknya ada ...") is still decided by the list.
- "Saham apa yang harganya naik?" (a noun -nya after "yang") reads as having no reference: retrieved alone.

## Dependencies
ADR-021, ADR-014, `story_words.names / vocabulary / is_verb`, `web/nya_words.py`.
