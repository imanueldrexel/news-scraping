# ADR-031: The arc gates' word lists are frozen; NLI covers the class

**Status:** Accepted (owner, 2026-11-06)
**Date:** 2026-11-06
**Feature:** nli-faithfulness / newsletter-story-arcs
**Author:** 10x-Team (CTO + QA + Architect)

## Context
The arc fact gates (`causal_check`, `source_check`, `story_arc` schedule cues) route a sentence by closed word lists. Each of the last three QA rounds (10-19, 10-20, 11-06) sent back held-out synonyms, dev widened the lists, and the next sweep found more frequent unlisted forms. All 4 regressions of the 11-06 audit (#440, #446, #448, #449) came from widening a list or a place rule. ADR-024 already decided that the lexicon gate stays but does not close the class, and that NLI (in shadow) is the class-level answer.

Measured 11-06: the held-out forms are frequent in source articles (berpeluang 2,097, bersiap 1,294, terindikasi 1,020, sepertinya 377, diselesaikan pada 210, disokong 195). In arc output (19 live editions, every arcs*/sys152 replay), they are almost absent. The only held-out form in arc prose is "segera diselesaikan pada akhir September" (arcs-v2, 2026-10-11). "rampung" appears only in Sekilas, which is identical in the arcs=0 and arcs=1 copies.

## Decision
1. **Arc gate lists change only for:**
   - (a) a **regression**: a true sentence refused, or a hole the previous commit closed, now open;
   - (b) an unlisted form **seen in arc output**: a live `*-ringkas.md`, a replay under `digests/preview/`, or an `nli_shadow` row.
2. A held-out form found only in source articles is an **accepted gap**. It is tracked to SYS-200 and to NLI promotion (ADR-024), not to a list fix. QA stops filing corpus-only synonyms against the arc gates.
3. **Applied 11-06:**
   - #441, #442, #443, #444 and #447 are closed as accepted gaps.
   - #445 stays open, narrowed to "diselesaikan pada" (rule b).
   - #440 and #446 (regressions) are fixed first.
4. **Scope:** the arc fact gates only. The Tanya Berita follow-up rules (#421, #422, #423, #448, #449) have no NLI backstop and are outside this ADR.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Corpus-frequency floor (>= 500 articles) | bounded; fixes the three largest forms | another dev+QA round; corpus frequency is not arc-output frequency; each widening risks regressions | measures the wrong population |
| Keep fixing every frequent form | closes each listed gap | never converged in 3 rounds; 4 regressions this round | the loop is the problem |
| Freeze with no exceptions | simplest | a form the writer actually uses would stay open | (b) costs little and targets real output |

## Consequences
### Positive
- Ends the send-back loop on synonyms; dev time goes to regressions, NLI and acceptance (#425).
- The evidence bar is the product's own output, not the corpus.
### Negative
- Fail-open risk stays for unlisted forms until NLI is promoted: an invented cause, end or schedule using an unlisted word could print.
### Risks
- The writer starts using an unlisted form. Mitigation: rule (b). QA greps each audit's live editions and replays for unlisted forms, and SYS-200's natural set scores every arc sentence.

## Dependencies
- ADR-024 (NLI shadow first), SYS-200 (#430) natural set.
- Constrains QA: arc-gate defects need output evidence or a regression.
