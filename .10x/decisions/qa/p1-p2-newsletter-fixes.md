# p1-p2-newsletter-fixes — QA

### 2026-10-04 — Audit of dev commits 74d2ca5..826730c (OPS-20, SYS-68, SYS-67, SYS-63)
**Verdict: nothing closed.** None of #136, #216, #215, #204 is labelled `status: ready-for-qa` or carries Done-when evidence, and the audit found defects.

**Gates**
- Unit: 1,789 passed, 5 skipped. Integration, live runs and scheduled-run evidence: not run.
- Independent mutants: 11 written by QA, 10 killed, 1 survived (`more_ignores_unclustered`). Tree verified clean afterwards.
- Wiring checked: `DigestPath.note` -> `log_crawl_complete(note=)`; cleaner applied to site/trafilatura/newspaper output; preview digest 94/94 summaries.

**Bugs filed**
| ID | # | Sev | Finding |
|---|---|---|---|
| SYS-71 | 219 | P2 | any 429 = daily quota; a rate-limit burst stops all summaries, footer says "kuota harian habis" |
| SYS-72 | 220 | P3 | cleaner deletes prose ("Lihat juga data BPS...", "(and/or)", "(yoy/qoq)" tails) |
| DBT-51 | 221 | P3 | `more` count after grouping unguarded (surviving mutant) |
| DBT-52 | 222 | P3 | SYS-63 commit churned EOLs in `utils.py` (141 lines, 63 real) |

**Per ticket**
- SYS-68 #216: code holds; blocked on SYS-71 and a ready-for-qa handoff.
- SYS-67 #215: Done-when "<=1 contaminated cluster/day" not met (dev admits); needs owner acceptance.
- SYS-63 #204: blocked on SYS-72 and the owner's stored-row repair decision.
- OPS-20 #136: split limit and quota warning OK; extraction still on Gemini 20/day until SYS-39.

**Not verified:** 07:00/19:00 scheduled-run evidence for bot UA, host pacing, retries (SYS-66, SYS-70).
