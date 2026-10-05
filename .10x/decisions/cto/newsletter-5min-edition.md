# CTO decision 2026-10-05: tuning the 5-minute edition after the replay

Context: the SDE built tracker #244 and replayed it on 2026-10-04 / 10-03 / 09-28 (EXPERIMENTS.md 2026-10-05). SYS-82 #239 and SYS-83 #240 missed targets; the owner was asked four questions (AskUserQuestion) and aligned on the framework below ("Yes, and build it now").

All four are two-way doors (code/prompt, one commit to revert; no schema, no vendor). Blast radius: the daily edition; the full digest (archive) is unchanged.

| # | Decision (owner's answer) | Change |
|---|---|---|
| 1 | Focus: **general briefing, finance first** | None. No non-finance quota; finance-first stays a tie-break in the editor prompt. 10-04's 5/8 non-finance is correct. |
| 2 | Headline: **ask 10, accept 12** | Prompt keeps "maks 10 kata"; the code refuses a judul only above 12 words. |
| 3 | Coverage: **guarantee the day's 6 largest stories** | Candidates = top 3 per section + the 6 shown clusters with the most portals. A top-6 story that is not a top story always gets a Sekilas line: outside the 3-per-section cap, never trimmed by the word budget. |
| 4 | Duplicates: **word-overlap guard** | After the editor, a Sekilas line sharing >= 3 content words, one of them a name, with a top story is hidden (pairwise vs top stories, never a merge); counted in `_edition`. A hidden top-6 story counts as shown via its twin. |

CTO calls (no question needed):
- SYS-82's ">= 90% accepted first try" is retired: it was a cost proxy and the retries cost ~$0.01/day. Reliability = ">= 95% after the retry".
- Tracker criterion 6 becomes a dollar cap: newsletter LLM cost <= $0.05/day (was "calls no higher than today").

Alternatives rejected: a non-finance cap (owner wants a general briefing); "12 words" in the prompt (the model aims at the number and overshoots); top 4 per section (a 5th-ranked big story still slips); prompt-only duplicate fixes (the model ignored two prompt changes in the replay); embedding/cluster merging (SYS-67 settled it cannot separate angle from topic).

Trade-offs accepted: headlines up to ~3 phone lines; 1-3 more Sekilas lines on a crowded day; the guard occasionally hides a related-but-distinct Sekilas line (still in the archive).

Risks: guard over-firing (counted; QA reviews hidden lines); top-6 guarantee pushing past 1,200 words (replay editions 869-949; the budget trims non-guaranteed Sekilas first, then logs and ships).

Success criteria (QA, first 7 scheduled editions): <= 1,200 words; >= 95% after retry; >= 5 of the 6 largest stories shown daily; 0 events shown twice; <= 1 wrong hide by the guard; newsletter cost <= $0.05/day. Review after those 7 editions, or sooner if a criterion fails twice.

Timing: ~3 h dev + one replay (~$0.05), built the same session (owner). The 2026-10-06 12:00 run may ship whichever build is committed by then.
