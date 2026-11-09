# QA: newsletter 5-minute edition (tracker #244), 2026-10-05

Full report: `.10x/reviews/2026-10-05-qa-report.md`. Scope: the 9 tickets of tracker #244 (SYS-80..85, OPS-41..43), as built in commits 654a81e..fdae116.

## Test strategy (risk-based)
The dev's unit suite is strong at the code level, so it was taken as a baseline and not as evidence. QA's own checks target what a unit test of the existing code cannot see:
1. **Black-box tests from the tickets' wording** (`scripts/experiments/qa_newsletter_244/test_qa_newsletter_edition.py`, 49 tests). They drive the real chain: generator → digest + edition → phone/A4 PDF (read back with pypdf) → Telegram message. A scripted LLM marks articles `tidak_terkait`.
2. **Heuristics measured on real data:** the SYS-83 echo guard over all 2,016 top-story × story pairs of the three replay digests (`probe_echo_real.py`).
3. **Real output read as a reader:**
   - the three v5 replay editions and digests, against every word limit and quota (`check_real.py`);
   - a read-only DB spot-check of suspicious facts (Destry's title, the Korea "Mengapa penting", the Haji Isam/FORU story);
   - HTML entities in stored headlines.
4. **Independent mutants** (`qa_mutants_244.py`, 57): one per ticket promise, run in a git worktree on the real venv interpreter, with an unmutated baseline first.

## Verdicts
| Ticket | Verdict | Why |
|---|---|---|
| SYS-81 #237 | close | 12 months / 7 days; no English month or ISO date in either file, either PDF or the message |
| OPS-41 #238 | close | all 3 real A4 PDFs: no page starts on a source/link line or ends on a heading; mutants killed |
| SYS-84 #241 | close | copy table, degraded notice at the top, empty day, brands for every WebsiteName; no enum/telemetry in real files |
| SYS-85 #245 | close | keys ⊆ WebsiteName; old-key mutant killed |
| SYS-80 #236 | **sent back** | the v5 re-render of 2026-10-04 again has the "10 Saham Paling Babak Belur" link under a Haji Isam headline, with a FORU bullet from that article (DB: neither article names the other's subject). The Done-when names exactly this link |
| SYS-82 #239 | held | owner hand-check of 20 stories pending; SYS-87 filed |
| SYS-83 #240 | held | owner phone read + first scheduled run (2026-10-06 12:00); SYS-86 must be fixed before closure (no bug carryover) |
| OPS-42 #242 | held | owner phone confirmation; everything else verified (105×228, 11.5 pt, links, contrast on the real backgrounds) |
| OPS-43 #243 | held | needs 3 scheduled 12:00 runs (first 2026-10-06); OPS-44 filed |

## Bugs / tickets filed
- SYS-86 #246 (P2): the echo guard hides distinct events. Titles, place halves, programme names, months and `Rp2` tokens count as "names". At least 11 of 27 flagged real pairs are different events.
- SYS-87 #247 (P3): the number guard ignores the decimal position (`Rp1,5` = `Rp15`); outlet-name digits sit in its corpus.
- OPS-44 #248 (P3): the reader is promised a PDF when its upload then fails.
- SYS-88 #249 (P3): 311 stored headlines carry HTML entities; the reader sees `&amp;` in archive link labels.
- DBT-56 #251, DBT-57 #252, DBT-58 #253 (P3): mutant survivors.
  - The empty-terkait refusal: without it, an answer marking every article unrelated crashes the run.
  - The 1,200 budget, top-3 candidates and `[`/`]` escaping.
  - The PDF escape: without it, a "<" fails the render.
- SYS-89 #250 (enhancement): the edition repeats the previous edition (BSU is a top story on 10-03 and 10-04; ~9 of 32 items).

## Coverage gaps that remain
- Model-dependent outcomes (`terkait` judgement, editor picks) are only checked by replays, and replays are not deterministic. SYS-80 passed on v4 and failed on v5. Watch `_summaries` and read the editions of the first scheduled days.
- Telegram delivery is only fake-tested until 2026-10-06 12:00.

## Lessons
- A heuristic validated on the days it was tuned on is not validated. Measure it on all pairs and on untuned days.
- The MAX_PATH trap hit again: the first mutant run "killed" everything at collection. Valid re-run: 49/57 killed, 5 real gaps, 3 equivalent. Always print the unmutated baseline and the kill reason.
