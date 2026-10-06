# QA pass 2026-10-06 (night): P3 burn-down + tracker #244 fixes

**Scope:** the two dev batches nobody had verified: 2febd2d/816486f/c883e04 (SRC-58, OPS-39, DBT-01, SYS-90) and 468b75d..41a3ab6 (SYS-86, SYS-80, SYS-87, OPS-44, SYS-88, DBT-56..59). Report: `.10x/reviews/2026-10-06-qa-report.md`.

## Test strategy
- Done-when first, then the diff.
- Suites: unit 2,434 / integration 187.
- Mutants: dev's 69 plus 15 QA ones, in a short-path worktree, with baselines printed and errors counted INVALID.
- Read-only production checks: DB counts, both FAISS docstores, live sitemaps, the first real edition read as a reader would.

## Decisions
| Ticket | Verdict | Why |
|---|---|---|
| SYS-90, OPS-39, DBT-01 | closed | Done-when met on production and in tests. Residuals filed (SYS-91, DBT-60) |
| SYS-86, SYS-80, SYS-87, OPS-44, SYS-88 | closed | Done-when met. The first real edition (10-05 rebuild) shows 0 hides, 0 duplicate events, 0 number refusals, 1 subject refusal |
| DBT-56..59 | closed | Named mutants killed in QA's run |
| SRC-58 | held | Needs the 2026-10-07 07:00 crawl (today's runs predate the fix) |

## Bugs filed
- SRC-59 #260 (P2): INVESTORID's `sitemap_news.xml` 404.
- SYS-91 #257 (P3): FAISS 1970 dates.
- DBT-60 #258 (P3): validator misses the str/float forms.
- OPS-46 #259 (P3): integration tests queue alerts into the real Telegram outbox.

## Quality gates for the next QA
- **SRC-58:** the 07:00 crawl_log notes and PIKIRANRAKYAT's phase time.
- **OPS-43 #243 and the tracker's 7-edition criteria:** the 10-06 12:00 edition was degraded (SumoPod cap) and does not count; the 10-05 rebuild was manual.
- Any integration run until OPS-46 is fixed: check `logs/telegram_outbox.jsonl` afterwards.

## Lessons
- A repair of a derived value must cover every store holding a copy (articles, FAISS metadata).
- Probe a boundary validator with each type the stores hold.
- Never call a mutant equivalent before it survives the full `tests/unit`.
