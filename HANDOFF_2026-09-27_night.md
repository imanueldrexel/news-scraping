# QA handoff — the QA list of `44df5b7`, worked (2026-09-27, night)

Paste this as the opening prompt of a QA session, or point the session at this file. It answers the QA audit of `HANDOFF_2026-09-27.md` (`44df5b7`, 6 tickets #190–#195).

- **All six are worked and closed:** SYS-56 (P1), SYS-57, OPS-33, OPS-32, SYS-58, DBT-47.
- **One new bug, filed and closed:** SYS-59 (#196). It was in my own SYS-56 fix, found while working SYS-58, and never shipped.
- **Left open, as QA asked:** SYS-54 (waits for VIVA's first `removed N vector(s)` line), SYS-52, OPS-28, SRC-54 (tonight's 19:00 run counts as one clean run each; that evidence is QA's to record).
- **Mutation runner:** 69 KILLED / 0 SURVIVED (69).
- **Nothing here has run in a scheduled crawl yet.** The next run is 2026-09-28 07:00. Every test used tmp indexes, the test DB, or read-only queries on the live DB, plus one `build_crawler_api()` on the live indexes with the network cut (read-only; it builds the crawler and exits). **Read the risk list first.**
- **Owner action, still needed:** revoke the Telegram bot token in @BotFather (`/revoke`), put the new one in `.env`, and test with `venv\Scripts\python.exe scripts\notify_telegram.py "test"` (OPERATIONS.md, "The token is a password"). The leaked copy in `logs/` is scrubbed, but the old token was on disk and must be treated as known.

Before touching anything, read in this order:

1. `CLAUDE.md`: the FAISS paragraph gains SYS-56 (the journal) and SYS-57 (the sweep). The ID map now runs through #196.
2. `HANDOFF_2026-09-20.md`: the **Hard rules** still stand.
3. `EXPERIMENTS.md`: the four new or rewritten trap lines, then the entry dated 2026-09-27 at the bottom ("SYS-56..59 / OPS-32 / OPS-33 / DBT-47").
4. `OPERATIONS.md`: "FAISS index corrupt or won't load" (rewritten; **never delete a `NEWS_L*.commit` directory**), "The crawl cleans up what it settles itself" (SYS-57), "A network outage does not stop the worker from being built" (OPS-32), "The token is a password" (OPS-33), and two new env vars.
5. The closing comment on each ticket, which has the evidence for its Done-when.

---

## Suites and tree

| | at your audit (`44df5b7`) | now |
|---|---|---|
| `tests/unit` | 1,374 passed, 5 skipped | **1,421 passed, 5 skipped** |
| `tests/integration` | 127 passed | **127 passed** |
| `qa_mutation_runner.py` | 40 killed / 0 survived (40) | **69 KILLED / 0 SURVIVED (69)** |

Commits on `dev`, **not pushed**:
- `d824700` SYS-56
- `50c6888` SYS-57
- `3b3046a` OPS-33
- `7a5c9c7` OPS-32 and `98068df` (an OPS-32 test the runner found weak)
- `8517c5e` SYS-59
- `de56abf` SYS-58
- `c9d5a56` DBT-47
- the docs commit with this file

---

## Closed

| Ticket | What changed | Evidence (on the ticket) |
|---|---|---|
| SYS-56 #190 (P1) | A save stages the new pair and a copy of the old one (`*.bak`) in `NEWS_L*.tmp`. It commits with **one directory rename** to `NEWS_L*.commit`, then moves the files into place. `load_index` and every save roll an interrupted commit forward under the save lock before anything else. `load_index` refuses a pair whose positions and mapping disagree (`CorruptIndexError`). The store check has a new check, `faiss_pair_mismatch`, read under the save lock. The `_atomic_save_local` docstring no longer claims append-only. | QA's repro is now the test, run at all 7 kill points. Before: `ntotal=6 mapped=5`, `d2->d3`, `d5->KeyError`. After: every query right. Live store check: 0. |
| SYS-57 #191 | The cleanup candidates come **from the store**: this source's sitemaps with no article, `rejected_filter` or at the fetch cap, that still have chunk rows (`terminal_with_chunks`, 33 ms for VIVA). They are swept when the source's block opens (what a killed run left) and after its last batch (what this run settled). The in-memory candidate sets are gone. | The ticket's test: real service over the real repository, killed in batch 2, then the next run leaves no vectors and no rows |
| OPS-33 #194 | `notify_telegram` logs every exception and API body through `redact()`: the configured token anywhere, plus anything shaped `bot<id>:<secret>`. `run_scheduled_crawl._notify`'s fallback does the same. | Test with `/bot123:ABC.../sendMessage` in a `ConnectionError`; the log leak is scrubbed; the grep is empty; the token is not in git history |
| OPS-32 #193 | (1) Every model loads from its local snapshot directory (`core/utils/hf_cache.resolve_model`), at all three load sites. (2) `SourceWorker.run` returns `init_failed`, and 2 in a row stop the run with one `STOPPED:` reason. (3) A failed alert is retried after 5 s and 20 s, then queued in `logs/telegram_outbox.jsonl` and delivered first by the next send. | With the network cut: MiniLM before, `ProxyError` after 78 s; `build_crawler_api()` after, built in 17.6 s |
| SYS-58 #192 (P3) | A failed or refused flush keeps its discards (`_unsaved_discards`). The next block deletes their vectors again before its flush and their rows after it. No row is deleted on a failure path. | Both cases fail on HEAD~ and end with the store check at zero after the fix |
| DBT-47 #195 (P3) | A spy asserts that the run-lock check sees the save lock held, probed from a second handle. A test covers `AccessDenied` meaning "not the owner". The runner has the true-move mutant and the AccessDenied mutant. | Both killed by assertions |
| SYS-59 #196 (new, P3) | The journal carries an owner id, so a writer whose own roll-forward failed (a scanner holding `index.faiss`) finishes that commit as its own instead of refusing itself as stale | Repro test: before `['a','b']` plus `StaleIndexError`; after `['a','b','c']`; a foreign journal is still refused |

---

## Risk list — read this first

**1. The FAISS on-disk protocol changed, and it has not run live yet.** The first scheduled save is 2026-09-28 07:00. In that run's log, check:
- no `CorruptIndexError` and no `finished a save that was interrupted` line, unless something really was killed mid-save;
- no `NEWS_L1.tmp`, `NEWS_L2.tmp`, `NEWS_L1.commit` or `NEWS_L2.commit` left in the repo root afterwards;
- `index.faiss.bak`/`index.pkl.bak` timestamps move together;
- the store check shows `faiss_pair_mismatch 0`.

Each save now also copies the old pair into the stage before the commit (the same bytes as before, the `.bak` copy) and fsyncs the staged files. Expect flushes to be slightly slower than on 2026-09-26/27.

**2. `load_index` now refuses a mismatched pair.** This covers the web app too, since it loads through `ChunkFAISSDatasource`. If a pre-SYS-56 torn pair existed anywhere, the crawler would now fail to start. With OPS-32 it would stop after 2 failed starts, with the reason in the summary. The live pair measured whole tonight (store check 0).

**3. Models are pinned to the cached snapshot.** A cached model is never updated from the Hub, which is deliberate: the probe was trained on that encoder. MiniLM has two snapshots in the cache, and `refs/main` picks `e8f8c21…`, the one sentence-transformers used online anyway. A model that is not cached is still downloaded, with a WARNING. Delete the cache and the old behaviour returns.

**4. The SYS-57 sweep runs twice per source.** When the block opens, it runs after the NULL-row re-embed, so nothing it discards is re-added. At the end, it runs after the fetch failures are counted. Each run is one SQL query (33 ms for VIVA), plus a docstore scan only when it finds something. The SYS-54 closure line is byte-identical: `VIVA: removed N vector(s) of sitemaps settled terminal this run (SYS-54)`. A second line can appear: `... an earlier run settled terminal (SYS-57)`.

**5. Not covered by the SYS-57 sweep:** vectors of a terminal sitemap that has **no** chunk rows. The store check reports these as `l1/l2_no_chunks`, and the repair removes them.

**6. The circuit breaker counts `init_failed` in a row across both phases.** A successful start resets the count. A source failing on its own never counts. There is no "wait for the network and retry": with (1) the build does not need the network. `SCHEDULE_FAILED_STARTS_BEFORE_STOP` changes the threshold.

**7. The Telegram outbox is new shared state.** It lives at `logs/telegram_outbox.jsonl`, keeps the newest 20 alerts, and is guarded by a filelock. A 4xx is never queued, and a queued alert the API later refuses is dropped with its text in the log. The CLI test message is never queued. All three senders (the crawl summary, the health check, the backup) go through it.

---

## What to mutation-test

All 69 are KILLED. There are 29 new ones: `sys56_*` (7), `sys57_*`, `sys58_*` (4), `sys59_*` (2), `ops32_*` (11), `ops33_*` (2), `sys53_run_lock_moved_outside_save_lock`, and `ops31_access_denied_escapes`. Three of the old ones were re-targeted after SYS-57/58/59 changed their lines, and two SYS-54 ones were rewritten for the store sweep. `sys53_run_lock_outside_save_lock` is renamed `sys53_run_lock_check_deleted`, which is what it does. It still dies by the 120 s timeout, not by an assertion: under `-x` an earlier test hangs before DBT-47's spy runs. The true move, which is the one QA asked for, dies by an assertion.

**Not covered by the runner (`tests/unit` only):**
- the new SQL `terminal_with_chunks`, whose arms (source, `EXISTS chunks`, the cap) only `tests/integration/test_discard_terminal_embeddings_live.py` kills;
- the `_fsync_files` call before the commit rename, which no test can observe without a power loss.

## Traps worth more than the tickets

- **A mutation run that "kills" everything in 3 s is a broken environment, not a strong suite.** Through a venv junction under the long scratchpad path, site-packages paths passed MAX_PATH. Every mutant died of the same collection error. Run the unmutated clone first.
- **HF_HUB_OFFLINE turns a slow failure into a fast one on transformers 4.57.3; it does not make loading work.** Load from the snapshot directory.
- **A journal without an owner misreads your own interrupted commit as a foreign save (SYS-59).**

## Production writes this session

- `logs/scheduled_crawl_2026-09-27_0700.log`: the one token occurrence was replaced with `bot<redacted>` (OPS-33 Done-when). No database write. No FAISS write: `build_crawler_api()` loads the indexes but does not save them.
- Read-only: `check_store_consistency.py` (report written to the scratchpad, not `crawler_health/`), and one `EXPLAIN ANALYZE` SELECT.

## Decisions waiting on the owner

1. **Revoke the bot token** (OPS-33). This cannot be done from code.
2. SRC-10, SYS-51, SRC-03/BISNIS: unchanged from the previous handoff.
