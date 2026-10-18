# sde decisions — index

## Active features
- [qa-1013-queue](qa-1013-queue.md) — 2026-10-19: built QA 10-13 queue: nya_words + refers_to_thread (ADR-021), -nya roots, FTS unique key, numeric dates, sitemap_state, INVESTORID section; e6637a9, 6c934c0
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) — OPS-20/SYS-68/SYS-67/SYS-63 built; QA feedback SYS-71/72, DBT-51/52 fixed 2026-10-04; ready-for-qa

- [newsletter-digest-quality](newsletter-digest-quality.md) — SYS-69, SYS-65 ready-for-qa; OPS-38 code done, job not registered (owner)
- [sys-39-knowledge-extraction](sys-39-knowledge-extraction.md) — provider/cost/peak guards built (ADR-003); 0.85 gate and prod migration need the owner; not closed
- [body-cleaner-and-repair](body-cleaner-and-repair.md) — SYS-75 fixed (ready-for-qa); SYS-73 dry run done, apply path waits for the owner; DBT-50 ready-for-qa

- [newsletter-5min-edition](newsletter-5min-edition.md) — tracker #244: SYS-80..85, OPS-41..43 built 2026-10-05 (structured summaries + guards, editor pass, copy module, phone PDF, Telegram message); replayed on 3 days; SYS-82/SYS-83 targets partly missed, owner decisions listed. QA's findings fixed the same night (SYS-86/80/87/88, OPS-44, DBT-56..59); SYS-88's backfill applied 2026-10-06

- [p3-bug-burndown-2026-10-06](p3-bug-burndown-2026-10-06.md) — SRC-58, OPS-39, DBT-01, SYS-90 (found) ready-for-qa; two owner-approved production writes with backups; SRC-47 owner-deferred, re-measured

- [newsletter-story-arcs](newsletter-story-arcs.md) — tracker #336: DBT-72..75, SYS-147..150 built 2026-10-13 night (arcs behind NEWSLETTER_ARCS=0); DBT-76 split out; SYS-150 replay for the owner's blind read; 2026-10-14: SYS-154..160 (arcs read as stories) ready-for-qa, final replay 18/20, date-led 72%→7.8%; 2026-10-15: QA rework SYS-157/158/162/163/164 + DBT-77 ready-for-qa, SYS-161 waits on a ~$0.15 re-run after the SumoPod top-up; 2026-10-16: SYS-164 rework (sejak <bulan> frame), SYS-165 (future-time agenda repeat), SYS-166 (future times schedule an agenda), DBT-78 (QA survivors) ready-for-qa; 2026-10-16 evening: SYS-167..170 (future times checked against today's articles, change claims in three forms), DBT-79, DBT-80 (registry 0 stale + hygiene test) ready-for-qa; 2026-10-16 night: SYS-169 rework (future phrases judged by key only), SYS-171 (weekday + "ke depan" windows), SYS-172 ("ke N" change claims), SYS-173 (week parts) ready-for-qa; 2026-10-16 late night: SYS-171 rework (weekday of a week), SYS-174 (running spans by field), SYS-175 (adjacent "mencapai"), SYS-176 (weekday-dated running periods) ready-for-qa; 2026-10-18: QA's 10-18 queue (ADR-020: every word of a causal half covered, market verbs, negators/denials/hedges, lists; SYS-186/191/193 end points, SYS-177 cue by clause, SYS-190 future periods, DBT-83) 13 ready-for-qa

## Cross-cutting SDE notes
- A unit test that patches only `init_crawler` while the code builds `build_newsletter_service()` runs the real generator and writes into `digests/` (2026-10-13: 2026-10-03.md overwritten). Patch the light service, make the heavy one raise.
- Measure a guard change on stored replays first (`digests/preview/replay*/*-stories.json` hold shown articles, refused raw answers and accepted stories): zero LLM cost, exact old-vs-new counts.
- PowerShell does not pipe a here-string into `git commit -F -`; write the message to a scratch file and pass its path.
- A replay that spawns one process per date imports the code at each start: never edit source between dates (it mixes versions), and never run `qa_mutation_runner.py` at the same time (it mutates files in place).
- PyMuPDF is in `py -3.11` (not the venv): `scratchpad/contact.py`-style contact sheets are the quick way to look at a whole PDF.
- Edit regexes in `core/utils/utils.py` with the Edit tool, not heredoc Python (escape mangling). Check `git diff -w --stat` equals `git diff --stat` before committing a file with mixed line endings.
- The harness turns backslash escapes inside python heredoc strings into control characters (a lone CR once made git treat OPERATIONS.md as binary). Use Edit/Write for text with backslashes and scan for lone CR afterwards. Never rewrite a whole file's line endings; replace per region (LF first, then CRLF).
- Wait on background work with a Monitor `until grep ...` loop; do not edit tracked files while `qa_mutation_runner.py` runs (it restores by `git checkout`).
- Mutants in a worktree without the MAX_PATH trap: `subst M: <scratchpad>`, `git worktree add <scratchpad>\mutwt HEAD`, `mklink /J M:\mutwt\venv <repo>\venv`, run from `M:\mutwt`. A narrowed `QA_MUTANT_TESTS` set reports false survivors for code guarded elsewhere (OPS-40's in `test_notify_telegram.py`): re-run every survivor on the full `tests/unit` before calling it a gap.
- Replays spend the production SumoPod account (prepaid balance, shared with the 21:00 extraction and the 12:00 newsletter). Check the balance before a replay round, and never run one while the extraction is running.
- A module constant used as a default argument (`pick_articles(limit=MAX_ARTICLES)`) cannot be monkeypatched by name: patch `__defaults__` (DBT-59).
- [rag-search-redesign](rag-search-redesign.md) — tracker #272: all 11 built, ready-for-qa; 42 mutants; SYS-103 found
- [rag-keyword-search](rag-keyword-search.md) — SYS-103: IDF-weighted keyword match built (ADR-006), ready-for-qa; 25 mutants
- [rag-retrieval-quality](rag-retrieval-quality.md) — QA's 2026-10-07 findings: SYS-104..108, SRC-60/61, DBT-61/62, OPS-46 ready-for-qa; SYS-110/DBT-63 found+fixed, SYS-109 filed; 3 owner-approved prod repairs 2026-10-08 (ADR-007)
- Read the clock with PowerShell `Get-Date` (local, +07:00) or `date -u`. On 2026-10-12 Git Bash's plain `date` printed LOCAL time, and reading it as UTC put the session 7 h late. Plan around the 07:00/12:00/19:00/21:00 jobs from `Get-Date`.
- A mutation worktree made before DBT-63 checks fixtures out with CRLF: its unmutated baseline fails `test_repo_hygiene` (`1 failed, 1775 passed`), so a full-suite "kill" with that count is void. Run the baseline first.
- [chunks-fit-encoder-window](chunks-fit-encoder-window.md) — SYS-109: L2 windows of ≤ 80 words (ADR-008), L2-only corpus re-chunk, DBT-64 indexes; production re-chunk done 2026-10-09 00:30; SYS-109/DBT-64/SYS-111/OPS-47 ready-for-qa, SYS-112 open
- [ops-49-postgres-shm](ops-49-postgres-shm.md) — 2026-10-12: Postgres container shm_size 1gb (filter-drift audit DiskFull = 64 MB /dev/shm); recreated, counts identical, audit re-run
- [qa-senior-fixes-2026-10-12](qa-senior-fixes-2026-10-12.md) — 2026-10-12: SYS-111, SYS-139 (soft deadline, ADR-011), SYS-104+140 (LLM follow-up rewrite, ADR-010) ready-for-qa; rest in progress
- [qa-second-pass-fixes-2026-10-12](qa-second-pass-fixes-2026-10-12.md) — 2026-10-12 night: SYS-138 subject gate (ADR-013), SYS-143/144/145 (ADR-014), DBT-68/69, DBT-67 store_repair module (ADR-015); all ready-for-qa
- [open-p2-p3-2026-10-12](open-p2-p3-2026-10-12.md) — 2026-10-12 night: SRC-59 INVESTORID sitemap_post + id-segment placeholder hook, DBT-60 date rule, SYS-91 repair script (apply ~06:00)
- An LLM-writing gate is only as good as the guard's precision: replay, read every refusal detail in the log, and separate the model's faults from the guard's (SYS-154..159: 3 of the refusals were the guards').
- Long gh comment bodies: write them with the Write tool and pass `--body-file`; several heredocs in one Bash call broke the shell (unmatched quote).
- Causal gate (ADR-019, 2026-10-17): a claim matches ONE link of the quote by direction; sides are cut from the source sentences the quote covers; names may stand anywhere in the link's sentence, event words on their side. Measure every gate change on the replays (recheck_causes.py) before landing.
