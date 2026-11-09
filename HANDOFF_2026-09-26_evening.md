# QA handoff — the 2026-09-26 QA list, and the first clean scheduled run (2026-09-26 evening)

Paste this as the opening prompt of a QA session, or point the session at this file. It closes the QA audit of `HANDOFF_2026-09-26.md` (`0ec51ff`, 10 tickets #171–#180). All ten are worked. **Seven are closed**, plus one new bug found and fixed on the way (OPS-30 #181). **Three are open only for evidence that scheduled runs have not produced yet.** The 19:00 run was the first with all of this code in place, and it was clean: exit 0, 28/28 sources, 9,646 articles, store check all zero. **Read the risk list before the ticket list.**

Before touching anything, read in this order:

1. `CLAUDE.md` — workflow, commands, architecture, and the ID → `#N` map (now through #181). Two new facts in it: no stored `sitemaps.category` is a URL any more, and every FAISS-writing script must call the run-lock guard.
2. `HANDOFF_2026-09-20.md` — the **Hard rules**, which still stand.
3. `EXPERIMENTS.md` — **"Traps & settled questions"** first (two new lines), then the three entries dated 2026-09-26 at the bottom: SRC-54/OPS-30, SYS-52/OPS-25..29, SRC-53.
4. The closing comments on the tickets below. Each has the evidence for its Done-when.

---

## Suites and tree

| | at the QA audit (`0ec51ff`) | now |
|---|---|---|
| `tests/unit` | 1,259 passed, 5 skipped | **1,335 passed, 5 skipped**; also green in a fresh `git clone` with `core.autocrlf=true` (DBT-41) |
| `tests/integration` | 124 passed | **124 passed** |

Commits `ce9e1d4`, `f45c804`, `c4b8272`, `99f6c5b` plus this file, on `dev`, **not pushed** (dev is ~92 ahead of origin, as in earlier sessions).

---

## Closed

| Ticket | What landed | Commit |
|---|---|---|
| **OPS-25** (#174) | `check_store_consistency.py` splits "vector with no article" into **terminal** (a check, baseline 0) and **queued** (information only), using `repair_store_consistency._load_state`, so there is one definition of terminal. **Every baseline is now 0**: `l1_no_chunks 1335`-style baselines would hide that much new damage the same way `6529 KNOWN` did. The runbook says to run the check and then the repair after anything that moves rows to `rejected_filter`. OPS-04 (#52)'s closing claim is corrected in a comment there. Data half: the 1,237 VIVA orphans were removed before this session (`3d35a4c`). | `f45c804` |
| **OPS-26** (#175) | `newscrawler/tools/run_lock.py`. The scheduled run holds `.scheduled_crawl.lock` (its pid) from before `worker.start()` until the worker closes. The six FAISS-writing scripts exit 2 on their write path while it is held. `ChunkFAISSDatasource._atomic_save_local`, the chokepoint every FAISS save goes through, refuses any process except the lock's owner and its worker. A dead holder is stale and is taken over. **Live:** during the model load of a real run there were 0 `started` rows, and `repair_store_consistency.py --apply` exited 2. That is the window QA found. | `f45c804` |
| **OPS-27** (#176) | `logs/scheduled_crawl_<YYYY-MM-DD_HHMM>.log` gets the wrapper's lines and the worker's (tagged `[source-worker]`: funnel, filter telemetry, tracebacks via `logger.exception`, warnings). The newest 28 are kept, and the Telegram line ends with the path. **Verified on the 19:00 Task Scheduler run** (1.3 MB, every source's funnel line, SUMMARY). | `f45c804` |
| **OPS-29** (#180) | After the worker closes, the run calls `check_store_consistency` and writes `crawler_health/store-consistency-<date>.json`. The summary names each source with NULL-embedding rows and their counts (these heal on its next full_text), and lists any other growth as `STORE DIVERGENT`. **19:00 run:** `no growth`, all 10 checks zero, so no store part in the Telegram line, by design. | `f45c804` |
| **SRC-53** (#173) | `INewsCrawler.branch_name_from_url` (`re.match`, None otherwise). `fix_url_shaped_categories.py --website INEWS` renamed 657 rows to `inews-tv`, `inews-tv/talkshow`, `inews-tv/eksklusif` and `inews-tv/religi`. `inews-tv/talkshow` is **denied for INEWS** from sampled titles; `eksklusif` is mixed, so the probe decides. New store check `sitemaps_url_category`, baseline 0. **19:00 run:** talkshow 195 `rejected_filter` before fetch, 5 saved earlier and kept. | `99f6c5b` |
| **DBT-41** (#171) | `.gitattributes`: `tests/fixtures/*.jsonl text eol=lf`, `*.npz binary`. A fresh `autocrlf=true` clone gives the recorded gold sha `01c038e6…`, and `tests/unit` passes there. No retrain. | `c4b8272` |
| **DBT-42** (#172) | The raw CR in OPERATIONS.md is gone; a test fails on any bare CR in a tracked `*.md`. | `f45c804`, `c4b8272` |
| **OPS-30** (#181, **new**) | Found while verifying SRC-54. EmitenNews lists **scheduled posts dated today and tomorrow** at the head of its sitemap, and they soft-404 until published. `check_crawlers.py` sampled the first N, so it reported PARTIAL 0/3 every day and never extracted a real EMITENNEWS body. It now samples entries at least `HEALTH_SAMPLE_MIN_AGE_HOURS` (24) old first. Live: `OK 3/3 (2250ch)`. | `ce9e1d4` |

## Open — code done, waiting on scheduled runs

| Ticket | Done-when left | Evidence so far |
|---|---|---|
| **SYS-52** (#178, P1) | 3 consecutive scheduled runs with PIKIRANRAKYAT `completed` and `SELECT count(*) FROM chunks WHERE embedding_id IS NULL` = 0 after each. **Owner decided to wait** rather than lower the bar. | Run 1 (09-26 19:00): completed in 487 s, 319 saved, NULL rows 666 → **0**, no faulthandler output. The fix: `LXML_PARSE_LOCK` around `trafilatura.extract` and `Article.parse`; faulthandler in the worker; `worker process crashed (… 0xC0000005 access violation); stack (faulthandler) in <log>` instead of "killed by". Item 5 (flush every N batches) was **skipped on purpose**; the reasons are on the ticket. |
| **OPS-28** (#179) | After 3 scheduled runs, every HEALTHY source has a daily `full_text` row. | Run 1: order `WARTAEKONOMI, PIKIRANRAKYAT, …`; WARTAEKONOMI saved 912; nothing skipped by the budget. **MEDIAINDONESIA took 947 s** and survived only because of the new `SCHEDULE_SOURCE_TIMEOUTS=MEDIAINDONESIA=1200`. |
| **SRC-54** (#177) | After the re-queued sitemaps are crawled, the fleet cascade scan returns 0 for EMITENNEWS. | Code fixed (`own_paragraph_text`); owner-approved repair re-queued the 935 bad articles. Run 1: **996 saved, 0 cascaded**, median 1,904 chars (was ~9,000). About 1,000 re-queued rows remain. `check_crawlers.py` has a `REPEATED` status (the old extractor gives `REPEATED 3/3 (11953ch)` live). |

Checks for the next runs (09-27 07:00 and 19:00):
```sql
SELECT count(*) FROM chunks WHERE embedding_id IS NULL;                        -- 0 after each run
SELECT website, status, started_at FROM crawl_log WHERE task='full_text'
  AND started_at > NOW() - INTERVAL '1 day' ORDER BY started_at;               -- 28 rows per run, PIKIRANRAKYAT completed
```
The cascade scan is `core.utils.utils.is_cascaded(extracted_text.split("\n\n"))` over every EMITENNEWS article (script in the SRC-54 EXPERIMENTS entry). Read the newest `logs\scheduled_crawl_*.log` for `crashed`, `fatal exception` and `Traceback`.

Other open items, untouched: SRC-03 (BISNIS, held by the owner), OPS-19 (#132, the 3-day schedule check; day 1 morning had the crash, evening was clean), SYS-51 (#170, now +8 INEWS gold rows), OPS-20.

---

## Risk list — read this first

**1. OPS-26 changes what a manual crawl does during a scheduled run.** A `__main__.py` or `process_event` crawl started while the scheduled crawl runs is now **refused at its FAISS flush** (`RunLockHeld` from `_atomic_save_local`). Its SQL rows stay `embedding_id NULL` until that source's next run re-embeds them, and its `crawl_log` row ends `failed`. That is intended, because two writers would overwrite each other, but it is new. Check that the refusal leaves only the repairable state (NULL rows, nothing pointing at unsaved vectors) with a real manual run started mid-schedule.

**2. The lock is a pid file, not an OS lock.** Liveness is `psutil.pid_exists`. A stale lock whose pid Windows has reused for an unrelated process looks **held**. Every FAISS writer then refuses, and the next scheduled run fails with `RunLockHeld` (loud, not silent). The fix is to delete `.scheduled_crawl.lock` by hand. Acquisition is check-then-replace, not atomic, so two runs starting in the same second could both take it. Task Scheduler's `IgnoreNew` and the 12 h spacing make that remote. Judge whether either needs more.

**3. Starvation order is only as good as `crawl_log`.** It sorts by the newest `completed` full_text. A source that fails every run (not killed, just `failed`) stays at the front forever and is retried first each time. That is arguably right, but it also costs time at the head of every run. The projection counts an unmeasured source at its full timeout and otherwise uses its last duration, which can be small (PIKIRANRAKYAT's June run was 130 s, tonight's 487 s).

**4. The run log is written by two processes.** The wrapper and the worker both append to the same file, and faulthandler writes to it through its own handle. The wrapper is quiet while the worker runs, so tonight's 1.3 MB log has no interleaving. `logging.captureWarnings(True)` also puts LangChain deprecation warnings in it (noise, not errors).

**5. SRC-54's repair deleted 935 articles** from all three stores and re-queued them. About 1,000 re-queued rows are not yet re-crawled, so those articles are absent from RAG until the next runs. The 58 EMITENNEWS `rejected_filter` rows were not re-queued: the probe reads title + body[:500], and a cascaded body's first 500 chars are the same text as the clean one's. **Re-verify that reasoning.**

**6. SRC-53 made two scope calls from titles.** `talkshow` is denied (promos plus debate-show clips, SYS-49/SRC-45 classes). `eksklusif` is left to the probe, which I saw pass one promo ("Jangan Lewatkan Interupsi Malam Ini …"): promo titles are a gap the probe does not close. The 5 talkshow articles saved before the deny were kept.

**7. `check_crawlers.py`'s `Totals:` line does not count `REPEATED` (or `STALE`)**, because its format is pinned by tests and parsed by the health-check wrapper. Such sources appear in "needs attention", and `REPEATED` sets exit 1, but the totals no longer add up to N. This predates the change for STALE.

---

## What to mutation-test

Mine, all KILLED (details in the EXPERIMENTS entry):

| Mutation | Expected |
|---|---|
| `running = _crawl_running(session)` → `running = 0` (QA's surviving mutant) | `TestRepairCrawlLogGuard` fails |
| repair's `refused_by_run_lock` guard → `if False:` | 2 fail |
| `refuse_foreign_writer()` removed from `_atomic_save_local` | 1 fails |
| `dedupe_chunks.py` guard → `if False:` | 2 fail |
| `faulthandler.enable(file=fh, …)` → `pass` | `test_a_native_crash_is_labelled_a_crash_and_leaves_a_python_stack` fails |
| `with LXML_PARSE_LOCK:` → `if True:` (trafilatura) | `test_trafilatura_extract_never_runs_on_two_threads_at_once` fails |
| the old EMITENNEWS extractor | 3 offline tests fail; live `check_crawlers` → `REPEATED 3/3` |

**Not yet mutated. Please do these:** `starvation_order` (sort by name instead), `timeout_for` (drop the `max`), `store_note`'s `chunks_not_in_faiss ≤ pending_sitemaps` exemption, `sample_order` (return the listing unchanged), `abandon_reason` (always "killed by"), `CASCADE_MIN_SUFFIX_CHARS` / `is_cascaded`'s `>= 2`, `SOURCE_SOFT_LEAVES["INEWS"]` emptied, the `sitemaps_url_category` SQL, and `RunLock.release` (remove unconditionally).

**Write your mutants so a surviving one cannot touch real data.** With `running = 0`, my first version of the repair test ran on into the real code path and copied the live NEWS_L1/L2 into `backups/` (686 MB) before failing on a stub. Live files were untouched (mtime and totals checked); the copy was deleted, and the test now monkeypatches `VECTOR_DB_NAME_L1/L2` and `BACKUP_DIR` to `tmp_path`. Check the other writer tests for the same exposure.

---

## Traps worth more than the tickets

**Count repeated text, not characters.** EMITENNEWS's 11,953-char bodies looked healthier than the real 2,250. `REPEATED` exists because a count cannot show this.

**A health check that samples "the first N listed" samples whatever the site puts first**, here unpublished posts that return soft-404.

**`ctypes.string_at(0)` does not crash on Windows**: ctypes turns the access violation into `OSError`. Use `faulthandler._read_null()` to test native-crash handling.

**The Bash tool's heredoc collapses `\\` escapes.** It put a literal newline into a test fixture and turned a `\\`-fix into a no-op, which is the same class of bug as DBT-42's CR. Write byte-sensitive edits from a file.

**`sed -i` over `scripts/*.py` rewrites every file's line endings** (CRLF → LF). Six unrelated scripts showed as modified. Check `git diff --ignore-cr-at-eol` before committing.

---

## Production writes this session (all owner-approved, all backed up)

| Write | Rows | Backup |
|---|---|---|
| SRC-54: cascaded EMITENNEWS articles removed from `articles` + `chunks` + FAISS, sitemaps re-queued | 935 articles, 8,042 chunk rows, 935 L1 + 7,107 L2 vectors | `backups/src54_20260926T075610Z/` (both indexes + `rows.json`) |
| SRC-53: INEWS URL categories renamed | 657 | `backups/src36_url_shaped_categories_20260926T082823Z.json` |
| Verification run: `run_scheduled_crawl.py --website ERAID` (no Telegram) | +0 / +0 | — |

## Decisions waiting on the owner

1. **SYS-51** — the gold-set refresh plus retrain now covers VIVA's 289 rows and INEWS's 8. `test_no_url_category_on_a_source_whose_crawler_names_its_branches` exempts `{"VIVA", "INEWS"}` until then.
2. **SRC-03 / BISNIS** — unchanged: keep, revisit via permitted access.
3. **OPS-19** — its 3-day check runs from 2026-09-26.

## How to report back

Per ticket: the Done-when checklist with evidence beside each item, the commit hash, and one line on what you would not trust yet. For SYS-52, OPS-28 and SRC-54, add the numbers from each scheduled run you saw, and close them if they hold. In the session summary: tickets closed, tickets blocked and on what, decisions waiting on the owner, and any new ticket with its number. If a closing claim turns out wrong, correct it in a comment on that ticket, not silently.
