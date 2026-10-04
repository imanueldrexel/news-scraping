# newsletter-digest-quality — SDE

### 2026-10-04 (evening) — SYS-69, SYS-65, OPS-38 built (branch dev)
- **SYS-69 #217** (1827752, 7e44741): `_top_links` picks one article per outlet (authority order, case-insensitive) and fills a third slot with the best outlet's second article only when fewer than 3 outlets covered the story; link label is `OUTLET: headline` (cut at a word, brackets escaped), not the digest date. 6 mutants killed. Labelled ready-for-qa.
- **SYS-65 #211** (9afe23d, 0113c5a): `build_sections` clusters per topic, then `_merge_across_sections` merges clusters of any topic within `NEWSLETTER_CLUSTER_DISTANCE` (average linkage by the sum-of-unit-vectors identity, one matrix product per pass; closest pair first, into the larger cluster's section, earlier `SECTION_ORDER` on a tie), then ranks/caps and recounts. Real replay of 2026-09-28 (`scripts/experiments/replay_cross_section_merge.py`): 2 cross-section pairs -> 0. Four existing test helpers turn the pass off (their stub vectors are labels). 7 mutants killed. Labelled ready-for-qa.
- **OPS-38 #212**: `task=newsletter` takes event `date` and defaults to YESTERDAY (a behaviour change from "today"); `scripts/run_scheduled_newsletter.py` (run lock first, exit 2; crawl_log via the service; Telegram line clean/DEGRADED/EMPTY/FAILED; run log). 12 mutants killed (one survivor exposed a test whose date equalled yesterday). **Not labelled**: the Task Scheduler job is not registered.

### Deviations from the ticket
- OPS-38 proposes 06:30; I recommend 12:00 (a 06:30 digest of yesterday misses what the 07:00 crawl fetches). Owner to decide.
- SYS-69's "regenerated digest has 0 repeated-source clusters" and SYS-65's "owner's SYS-40 read" need an owner-approved newsletter run; only unit tests and the offline replay were done.

### Tech debt created
- `_merge_across_sections` is O(k^2) per merge pass in the number of clusters (about 300 a day: milliseconds); revisit if a day exceeds ~3,000 clusters.
- A lock-refused scheduled newsletter (exit 2) sends no Telegram line (the generic exit-2 test forbids network); only Task Scheduler's Last Run Result shows it.

### Pitfalls found (for the next session)
- The harness turns `\r`/`\n`/`\b` inside python heredoc strings into control characters (a lone CR landed in OPERATIONS.md and EXPERIMENTS.md and made git treat the file as binary). Write regexes and paths with the Edit/Write tools, then check for lone CR bytes (`ord 13` not followed by `ord 10`).
- Whole-file line-ending rewrites make a 1,800-line diff of a 7-line change (DBT-52's lesson again): edit mixed-ending files with a replace that tries LF then CRLF, never `replace("\n","\r\n")` on the whole file.
- `pgrep`/`sleep N` do not work as waits here; use a Monitor with an `until grep` loop on the output file.
