# PM: nli-faithfulness
- **Problem:** closed cue lists miss unlisted synonyms; NLI can judge a sentence without the cue.
- **Scope v1:** shadow verdicts, eval set, measurements. No output change.
- **Success:** per-type recall / false-flag / hypothesis-only numbers; promotion verdict per type at recall >= 0.9 confirmed on the natural set; write-up if the numbers hold.
- **Non-goals:** refusal gate, DeepSeek as production judge, publishing the set.
- **Tickets:** SYS-197 #427, SYS-198 #428, SYS-199 #429.
