# PM: nli-faithfulness
- **Problem:** closed cue lists miss unlisted synonyms; NLI can judge a sentence without the cue.
- **Scope v1:** shadow verdicts, eval set, measurements. No output change.
- **Success:** per-type recall / false-flag / hypothesis-only numbers; promotion verdict per type at recall >= 0.9 confirmed on the natural set; write-up if the numbers hold.
- **Non-goals:** refusal gate, DeepSeek as production judge, publishing the set.
- **Tickets:** SYS-197 #427, SYS-198 #428, SYS-199 #429.
- **Tickets added:** SYS-200 #430 (natural set).

## 2026-11-11: owner decision, SYS-200 pilot on the rows already stored (option B)
- **Why:** every `nli_shadow` sentence is published arc prose that passed every lexical gate, so few may be unsupported. If 200 live sentences hold only 2-3 unsupported ones, the natural set can measure false flags but not recall. The pilot finds that out now, not after waiting until about 11-17 for 200 rows.
- **Pilot scope:** the 69 rows stored now (editions 11-03, 11-04, 11-05, 11-09).
  - Label: supported / unsupported by the cited quotes, by Claude and Gemini blind (ADR-026/027). The owner rules only on disagreements, in plain language.
  - Re-score offline with arm A and arm B v2 from `sentence` + `premise_ids`: the 11-03..11-05 rows predate #437's fix, so their stored scores are not used.
  - Report: labeller agreement, the unsupported share, the per-gate-family vs residual split, and the first per-type false flags and recall where there is support.
- **Then one owner decision:** if unsupported sentences are rare, the natural set's job is false flags only, and recall comes from SYS-197's targeted set plus QA's refused sentences (#413-#425). SYS-199's sign-off would rest on that split, stated openly.
- **Not in the pilot:** no edition change, the shadow stays on arm A, nothing is promoted. The rows are kept, and topped up to about 200 later.
- **Spend:** within SYS-196's $5 labelling cap; Gemini free tier preferred.
