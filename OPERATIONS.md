# NewsAggregator — Operations Guide

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_DB_PORT` | `5431` | PostgreSQL port |
| `POSTGRES_DB_USER` | `postgres` | DB user |
| `POSTGRES_DB_PASS` | `postgres` | DB password |
| `POSTGRES_DB_NAME` | `newsaggregator` | DB name |
| `GEMINI_API_KEY` | — | **Required for extraction, newsletter, RAG** |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model name |
| `DAILY_API_CALL_LIMIT` | `1400` | Hard stop for LLM calls/day, per model name in `api_usage_log`. **The Gemini free tier on this project enforces 20/day/model** (OPS-20, #136) — the 1400 is not what the API allows |
| `SOFT_THRESHOLD` | *(unset)* | SYS-37: overrides the probe artifact's CV-chosen P(soft) threshold (0.39 for the 2026-09-22 artifact, `newscrawler/core/models/importance_probe.json`). Leave unset unless OPS-18 says the operating point must move. The probe's encoder (`intfloat/multilingual-e5-large`, ~2.2 GB) is loaded by the crawler in addition to MiniLM. |
| `CHUNK_MIN_TOKENS` / `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `80` / `450` / `50` | DBT-13: whitespace-token bounds of the L2 paragraph chunks; `HierarchicalChunker()` reads them as its defaults and refuses `overlap >= max` or `min > max` at start-up. Changing them changes the L2 vector count (SYS-41). |
| `OPENAI_API_KEY` | — | OPS-20: OpenAI-compatible endpoint used **only** by the offline gold-set labeller (`scripts/label_filter_gold.py label`, SYS-36); never in the crawl path |
| `OPENAI_BASE_URL` | — | e.g. `https://ai.sumopod.com/v1` |
| `OPENAI_MODEL` | `deepseek-v4-flash` | Labelling model; a reasoning model is called with thinking disabled |
| `KNOWLEDGE_BATCH_SIZE` | `50` | Articles per extraction run |
| `EMBEDDING_MODEL_HF` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model |
| `VECTOR_DB_NAME_L1` | `NEWS_L1` | FAISS L1 index directory |
| `VECTOR_DB_NAME_L2` | `NEWS_L2` | FAISS L2 index directory |
| `DIGESTS_DIR` | `digests` | Newsletter output directory |
| `DBSCAN_EPS` | `0.25` | Cluster similarity threshold |
| `DBSCAN_MIN_SAMPLES` | `2` | Min articles per cluster |
| `RAG_TOP_K` | `5` | Chunks used for RAG answer |
| `SITEMAP_RECRAWL_COOLDOWN_DAYS` | `7` | Days before a sitemap with no `articles` row is offered to the article crawl again |
| `SITEMAP_MAX_FETCH_FAILURES` | `3` | SYS-09: runs that produced no article for a sitemap before `load_all_sitemaps` stops offering it; undo with `scripts/reset_fetch_failures.py` |
| `SITEMAP_SOURCE_FAILURE_RATIO` | `1.0` | OPS-15: the fraction of a run's attempted sitemaps that must fail before the run is considered source-wide (`1.0` = only when every one failed). Both this **and** `SITEMAP_SOURCE_FAILURE_MIN` must be met |
| `SITEMAP_SOURCE_FAILURE_MIN` | `20` | OPS-16: the minimum number of failures before a run can be called source-wide. A ratio alone is undefined at small N — with 3 rows left in a source's queue and all 3 dead, "100% failed" is evidence about those 3 URLs, not about the source, and sparing them meant they were re-fetched every run forever with no cooldown |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | Health-check alerts (OPS-01); unset = notifications skipped, logged only |
| `HEALTH_ALERT_ON_NO_CHANGE` | `true` | OPS-13: `false` mutes the daily alert on a red day whose per-outlet statuses all match the previous run (exit code unaffected; NEW/CHANGED/RECOVERED always notify) |
| `SCHEDULE_SOURCE_TIMEOUT` | `900` | OPS-19/OPS-22: per-source seconds before the scheduled crawl **kills** that source's worker process and moves on. The kill completes before the next source starts, the source's `crawl_log` row is closed as `failed` (`killed by run_scheduled_crawl: …`), and the next source gets a fresh worker (one more ~2 min model load) |
| `SCHEDULE_RUN_BUDGET` | `12600` (3 h 30 min) | OPS-22: no source is started once elapsed time + one `SCHEDULE_SOURCE_TIMEOUT` would pass this. The rest are reported as skipped, so the summary is sent before Task Scheduler's 4 h `ExecutionTimeLimit` kills the process silently. Keep it below that limit minus one timeout |
| `SCHEDULE_SOURCE_TIMEOUTS` | `MEDIAINDONESIA=1200` | OPS-28: per-source timeouts, `NAME=seconds,...`, never below `SCHEDULE_SOURCE_TIMEOUT`. The run budget uses the source's own timeout. MEDIAINDONESIA runs serially and took 880 of its 900 s on the first scheduled run (queue 11,460); a row cap instead would make its backlog permanent |
| `SCHEDULE_LOG_DIR` / `SCHEDULE_LOG_KEEP` | `logs/` / `28` | OPS-27: where the scheduled crawl writes `scheduled_crawl_<YYYY-MM-DD_HHMM>.log` (gitignored), and how many run logs are kept (two runs a day = 14 days) |
| `SCHEDULE_INIT_TIMEOUT` | `1200` | OPS-22: seconds the worker process may take to build the crawler (`init_crawler()`) before the start counts as failed |
| `DB_BACKUP_KEEP` / `DB_BACKUP_MAX_AGE_HOURS` / `DB_CONTAINER` / `DB_BACKUP_DIR` | `14` / `48` / *(auto)* / `backups/pg_dump` | OPS-23: dumps retained; the age at which the 05:30 health check alerts; the container to dump from (default: the one running container publishing `POSTGRES_DB_PORT`); where dumps go |
| `SCHEDULE_FULL_TEXT_WEBSITES` | *(unset = all)* | OPS-19: limits which scheduled sources get `task=full_text`. Was the gate for "no full_text until SYS-37"; SYS-37 landed 2026-09-22, so it is now the way to stage a source in listing-only |
| `SCHEDULE_ZERO_SAVE_RUNS` / `SCHEDULE_ZERO_SAVE_WITHIN_DAYS` | `3` / `7` | OPS-19: a source whose last N `full_text` runs **within that window** all saved 0 articles is named in the summary. The window matters — without it the check fires on history (WARTAEKONOMI's last three runs were 2026-06-01, all zero, while it holds 2,695 articles) |
| `HEALTH_SAMPLE_MIN_AGE_HOURS` | `24` | OPS-30: the health check samples listed entries at least this old first (then the rest). EMITENNEWS lists unpublished posts, dated today and tomorrow, at the head of its sitemap; they soft-404 until they publish |
| `HEALTH_STALE_LISTING_DAYS` | `7` | OPS-17: a listing whose newest `news:publication_date`/`lastmod` is older than this is reported `STALE` — serving, but not serving anything new. Needs attention, non-fatal (does not affect the exit code) |

---

## Running Tasks

All tasks are dispatched via `lambda_handler.process_event(event, None)`:

### Crawl a website (sitemap + articles)
```python
from newscrawler.application.api.lambda_function import lambda_handler
lambda_handler.process_event({"task": "all", "website": "BISNIS"}, None)
# Multiple websites:
lambda_handler.process_event({"task": "all", "website": "BISNIS,KOMPAS,CNBC"}, None)
```

### Knowledge extraction (Phase 2)
```python
lambda_handler.process_event({"task": "extract_knowledge"}, None)
```
Processes up to 50 unextracted articles per run. Safe to run repeatedly.

### Newsletter generation (Phase 3)
```python
lambda_handler.process_event({"task": "newsletter"}, None)
```
Generates today's digest to `digests/YYYY-MM-DD.md`.

To regenerate a specific past date, call directly:
```python
from datetime import date
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import SQLAlchemyNewsletterDataSource
from newscrawler.core.newsletter_generator import NewsletterGenerator

ds = SQLAlchemyNewsletterDataSource(SQLAlchemyClient())
gen = NewsletterGenerator(ds)
gen.generate(target_date=date(2026, 5, 20))
```

### RAG Search Web UI (Phase 4)
```bash
uvicorn newscrawler.web.app:app --port 8000
# Open http://localhost:8000
```

### Knowledge Base CLI query (Phase 2)
```bash
python -m newscrawler.tools.kb_query --ticker BBCA --days 30
python -m newscrawler.tools.kb_query --entity "Bank Indonesia" --days 7
python -m newscrawler.tools.kb_query --ticker GOTO --format json --output goto.json
```

---

## Database: container, backup, restore (OPS-23)

Production Postgres is a Docker container on port **5431**, database `newsaggregator`, Postgres **12.2**. Its definition is `docker/docker-compose.yaml` (restart `unless-stopped`, named volume `newsaggregator_pgdata`, container `newsaggregator-postgres`). A fresh volume is empty: restore a dump into it, or run `scripts/migrate.py`. Never bring back the old `docker/postgresql_tables/init.sql`; it predates every migration.

**Current state (migrated 2026-09-25 22:25 WIB, owner-approved):** production runs in `newsaggregator-postgres` from `docker/docker-compose.yaml`, data in the named volume `newsaggregator_pgdata`. Both `newsaggregator` and `newsaggregator_test` were restored from dumps, and all 10 tables matched the old container row for row. Verified by restarting Docker Desktop: the container came back on its own. Step 6 is done too: the owner removed the old container `docker-news-aggregator-postgres-local-1` and its anonymous volume on 2026-09-25, so the rollback is now the dumps in `backups/pg_dump/` (and `backups/faiss_*/` for the indexes). Never remove `newsaggregator_pgdata`.

**Backup.** `scripts/backup_db.py` runs `pg_dump -Fc` *inside* the container, so client and server versions always match and the host needs no Postgres install. It writes `backups/pg_dump/newsaggregator_<UTC stamp>.dump` (gitignored) and verifies it with `pg_restore --list`, which must show a TABLE DATA entry for sitemaps, articles, chunks, entities, entity_mentions and crawl_log. Only then does it prune to the newest `DB_BACKUP_KEEP` (default 14). A dump that fails verification is deleted, prunes nothing, sends a Telegram alert and exits 1. It finds the container as the one running container publishing `POSTGRES_DB_PORT`; set `DB_CONTAINER` to override. Registered daily at 05:00 as **"NewsAggregator DB Backup"**, with the same battery/wake settings as OPS-01 (command in the script's docstring). The 05:30 health check alerts when the newest dump is missing or older than `DB_BACKUP_MAX_AGE_HOURS` (default 48), because a backup job cannot report that it stopped firing. `venv\Scripts\python.exe scripts\backup_db.py --check` gives the same answer by hand. A dump is ~60 MB (2026-09-25: 152,928 sitemaps, 11,847 articles, 99,221 chunks). The FAISS indexes (`NEWS_L1/`, `NEWS_L2/`) are **not** in the dump. They can be rebuilt from `chunks` (`scripts/reset_faiss_index.py`) but are slow to re-embed, so copy them alongside a dump before any risky operation.

**Restore check** (safe, does not touch `newsaggregator` or the integration DB `newsaggregator_test`):

```bash
# Git Bash: MSYS_NO_PATHCONV=1 stops /tmp being rewritten to a Windows path
export MSYS_NO_PATHCONV=1; C=<container>; F=backups/pg_dump/<newest>.dump
docker exec $C createdb -U postgres newsaggregator_restore_check
docker exec -i $C pg_restore -U postgres -d newsaggregator_restore_check --no-owner < "$F"
# compare SELECT count(*) of the six tables against newsaggregator, then:
docker exec $C dropdb -U postgres newsaggregator_restore_check
```

Last run 2026-09-25 on `newsaggregator_20260925T140752Z.dump`: `pg_restore` rc 0, all six tables equal row-for-row.

**Moving onto the checked-in definition** (done 2026-09-25, steps 1–5; kept for a rebuild):

1. `venv\Scripts\python.exe scripts\backup_db.py`, then copy `NEWS_L1/` and `NEWS_L2/` aside.
2. `docker update --restart no docker-news-aggregator-postgres-local-1` then `docker stop docker-news-aggregator-postgres-local-1`. **Stop it, do not remove it.** It is the rollback, and its anonymous volume stays with it.
3. `docker compose -f docker/docker-compose.yaml up -d`, and wait for `docker inspect -f "{{.State.Health.Status}}" newsaggregator-postgres` to report `healthy`.
4. `docker exec -i newsaggregator-postgres pg_restore -U postgres -d newsaggregator --no-owner < backups/pg_dump/<that dump>`, then compare the six counts against the old container's (start it on another port if needed).
5. `docker restart newsaggregator-postgres`, then restart Docker Desktop itself. The container must come back **without** a manual start. `venv\Scripts\python.exe scripts\migrate.py` must report nothing to apply.
6. After a week of clean runs, `docker rm docker-news-aggregator-postgres-local-1` and `docker volume rm a3ebbe69…`. That is the only step that cannot be undone.

---

## Recommended Schedule (Windows Task Scheduler)

| Time (WIB) | Task | Command |
|---|---|---|
| 05:00 | Database backup (OPS-23) | `scripts/backup_db.py` — registered as **"NewsAggregator DB Backup"**, see "Database: container, backup, restore" |
| 05:30 | Crawler health check (OPS-01) | `scripts/run_scheduled_health_check.py` — registered, see below |
| after each crawl | Store consistency check (OPS-04, OPS-29) | runs inside `scripts/run_scheduled_crawl.py` after its worker has closed; writes `crawler_health/store-consistency-<date>.json` and puts anything to act on in the crawl's Telegram line. `scripts/check_store_consistency.py` by hand for the full table |
| 07:00 | Morning crawl (OPS-19) | `scripts/run_scheduled_crawl.py` — registered 2026-09-25 as **"NewsAggregator Scheduled Crawl (morning)"** (owner decision); first unattended run 2026-09-26 07:00. `python __main__.py` remains the manual equivalent |
| 06:45 | Knowledge extraction | task=extract_knowledge |
| 07:00 | Newsletter | task=newsletter |
| 19:00 | Evening crawl (OPS-19) | `scripts/run_scheduled_crawl.py` — registered as **"NewsAggregator Scheduled Crawl (evening)"** |
| 18:45 | Knowledge extraction | task=extract_knowledge |

### Scheduled crawl (OPS-19) — registered 2026-09-25

Two Task Scheduler jobs, **"NewsAggregator Scheduled Crawl (morning)"** (07:00) and **"(evening)"** (19:00), both running `venv\Scripts\python.exe scripts\run_scheduled_crawl.py` with the repo as the working directory. Settings: runs on battery and doesn't stop on battery, StartWhenAvailable, WakeToRun, a 4 h ExecutionTimeLimit, and `MultipleInstances=IgnoreNew`, so a slow morning run never overlaps the evening one. Inspect with `Get-ScheduledTask -TaskName "NewsAggregator*" | Get-ScheduledTaskInfo`. Verified the same night through a temporary task (`--website ERAID --phase sitemap`): LastTaskResult 0, crawl_log row 628 `completed` (+7), no leftover worker. Schedule on that date: 27 sources (HEALTHY minus VIVA; GRIDID retired). Pause it with `Disable-ScheduledTask -TaskName "NewsAggregator Scheduled Crawl (morning)"` (and evening).

`scripts/run_scheduled_crawl.py` is the scheduled entry point for the crawl itself. Two phases, in this order: `task=sitemap` for every scheduled source, then `task=full_text` for `SCHEDULE_FULL_TEXT_WEBSITES`. Listing first for everyone, so a slow source's fetch phase cannot delay another source's listing.

One model load in the normal case. `init_crawler()` costs ~2 min and ~4 GB RSS, so it runs once in a worker **process** (`newscrawler/tools/source_worker.py`) and the sources run one after another inside it. The wrapper process only dispatches, counts and reports. A source that exceeds `SCHEDULE_SOURCE_TIMEOUT` has its worker killed, and the kill finishes before the next source starts (OPS-22). This used to be a worker thread. Python cannot kill a thread, so the timeout never freed the caller, and an abandoned source would have kept writing the same service state and FAISS stores as the next one. A kill is safe for the stores: FAISS swaps are atomic (DBT-10), and chunk dedup is keyed on SQL (SYS-17/25), so a kill between the FAISS save and the SQL insert is repaired on the sitemap's next attempt. A killed source's `crawl_log` row reads `status='failed', error_msg='killed by run_scheduled_crawl: exceeded …'`. A worker that dies on its own reads `worker process crashed (exit code 3221225477 = 0xC0000005 access violation); stack (faulthandler) in logs\scheduled_crawl_….log` (a native crash) or `worker process died (exit code N)` (SYS-52). Nothing killed those; open the log. `SCHEDULE_RUN_BUDGET` stops starting sources in time to send the summary.

**Order (OPS-28).** `full_text` runs the source whose last *completed* `full_text` is oldest first (never-completed sources before all others). The first scheduled run proved the budget does not fit the whole fleet at 1,000 rows per source (11,372 s for 27 sources). A fixed alphabetical order therefore starved the same tail source every run (WARTAEKONOMI, skipped on 2026-09-26). Now a skipped source is first next time. Before the phase the run logs the order and the projected phase time from each source's last completed run. When the projection exceeds the budget, the summary says `full_text projected Ns > budget Ms`. The `sitemap` phase keeps HEALTHY order (7 minutes for all 28).

**Run log (OPS-27).** Every non-dry run writes `logs\scheduled_crawl_<YYYY-MM-DD_HHMM>.log` (`SCHEDULE_LOG_DIR`). It holds this process's lines (plan, order, per-source result and timing, SUMMARY) and the worker's (the per-source funnel `Full-text crawl finished … saved=N`, the filter's per-gate and keep-rate telemetry, SYS-34's first-save warnings, and a failing source's full traceback), tagged `[source-worker]`. `faulthandler` in the worker writes a native crash's Python stack of every thread there (SYS-52). The Telegram line ends with the log's path. The newest `SCHEDULE_LOG_KEEP` logs are kept.

**Run lock (OPS-26).** The run holds `.scheduled_crawl.lock` (the wrapper's pid, gitignored) from before the worker starts until the worker is closed. The worker keeps NEWS_L1/NEWS_L2 in memory for the whole run, and its next flush overwrites anything another process saved meanwhile. So every FAISS-writing script (`repair_store_consistency.py`, `requeue_cascaded_articles.py`, `dedupe_chunks.py`, `dedupe_sitemap_links.py`, `cleanup_offtopic_articles.py`, `recrawl_faiss_orphans.py`, and since DBT-43 `backfill_missing_articles.py`, `backfill_orphan_chunks.py`, `backfill_pending_embeddings.py`) exits 2 on its write path while the lock is held, and a manual `task=full_text`/`all` through `process_event` (`__main__.py`, the `lambda_handler` one-liner) raises `RunLockHeld` before it loads the models. `ChunkFAISSDatasource._atomic_save_local`, which every FAISS save goes through, refuses any process except the lock's owner and its worker. A second scheduled run refuses too (`FAILED to start … RunLockHeld`). A lock whose owner is gone is stale and is taken over: a Task Scheduler kill, a reboot or a power loss skips `finally`. Since OPS-31 (#184) the lock records its owner's process creation time, and "gone" means no process with that pid **and** that creation time. On Windows a dead run's pid is often live again under another program, and before OPS-31 such a lock blocked every run until deleted. The `RunLockHeld` message names the holding process. **Clearing a lock by hand:** if the message names a process that is not a crawl (Task Scheduler shows the task `Ready`, and no `python` process has `run_scheduled_crawl.py` on its command line), delete `.scheduled_crawl.lock` in the repo root.

**A manual crawl meets a newer index (SYS-53, #182).** The lock only says whether a scheduled run is going on *now*. A process that loaded NEWS_L1/L2 before or during the run and saved after it ended used to write its stale copy over the run's vectors. Every index a writer holds now carries the generation of the files it was read from (their file id, mtime and size), and `_atomic_save_local` refuses with `StaleIndexError` when the files on disk have changed since. Check and swap run under a per-index OS file lock (`NEWS_L1.lock`/`NEWS_L2.lock` in the repo root, gitignored; the OS releases it when the holder dies, so it never goes stale). What a refused **crawl** does: it logs `another process saved this index after this one loaded it; dropping this process's unsaved vectors and reloading the index` at ERROR, the source is `failed` in `crawl_log` with the `StaleIndexError`, and its chunk rows keep `embedding_id NULL` (the store check shows them as pending). The process's next source works on the reloaded, current index, and the refused source's rows are re-embedded at the start of that source's next `full_text`, the same repair as a killed source. Nothing is lost, only delayed. A refused **script** exits with the error before any SQL write that follows its save: rerun it. A restore from `backups/` is a change too, so every process that loaded the index before the restore is refused. This also covers two manual crawls, which no lock ever did. The per-source `crawl_log` 'started' row did not cover the model load or the gaps between sources. On 2026-09-26 15:13 the repair refused during the model load with no `started` row, the window the old guard missed.

**Store check (OPS-29).** After the worker has closed, the run calls `check_store_consistency` (read-only, seconds) and writes `crawler_health/store-consistency-<date>.json`. A source that crashed or was killed mid-run leaves chunk rows with `embedding_id NULL` (DBT-10 writes ids only after the source's flush). The summary names it with its counts, e.g. `vectors pending (re-embedded on the source's next full_text): PIKIRANRAKYAT 269 articles/666 chunk rows`; these heal on that source's next `full_text`. Any other check that grew is `STORE DIVERGENT: <check> <count>`, and that needs `repair_store_consistency.py`. A store check that itself fails is reported (`store check FAILED: …`) and does not change the exit code.

**VIVA was excluded** until SRC-33 (#119) landed on 2026-09-26 (branches keyed by name, soft leaves denied, backlog settled). It is scheduled now. `DEFAULT_EXCLUDED` in the script is the mechanism for the next source that needs holding back: every entry must cite its open ticket, and `--website` cannot override it.

**Queue size, net of category-denied rows** (SYS-50, measured 2026-09-25 with `scripts/experiments/probe_queue_net_of_denied.py`; eligibility is `load_all_sitemaps`' own predicate). Since SYS-50 a row whose category the gate denies is settled `rejected_filter` **before** the fetch, so it no longer spends one of the 1,000 per-run fetches. Across the 28 scheduled sources: **73,292 eligible, 15,846 (22%) denied, 57,446 left to fetch.** Largest shares: MEDIAINDONESIA 12,070 → 6,276 (48% denied; it runs serially, so this is its biggest saving), DETIK 14,926 → 9,739 (35%, SRC-50's leaves), JPNN 2,649 → 1,822, TVONENEWS 934 → 424, SINDONEWS 708 → 333, GRIDID 434 → 0 (every GRIDID brand is denied, see SRC-52 #169). Per run each source still fetches at most 1,000. The first `full_text` after SYS-50 settles every denied row among its 1,000 without fetching them, so a heavily denied queue drains faster. `scripts/reject_denied_categories.py --dry-run` settles the whole backlog in one go instead.

Summary line (Telegram, via the OPS-01 notifier): `N sources, +X sitemaps, +Y articles, Z with 0 saved`, then failures by name, then any source that has saved nothing for `SCHEDULE_ZERO_SAVE_RUNS` runs, then what was skipped, then the budget projection when it does not fit, the store check's findings, and `log <path>`. Exit code 0 when every source completed, 1 when any failed or timed out.

```powershell
venv\Scripts\python.exe scripts\run_scheduled_crawl.py --dry-run          # print the plan, crawl nothing
venv\Scripts\python.exe scripts\run_scheduled_crawl.py --phase sitemap
venv\Scripts\python.exe scripts\run_scheduled_crawl.py --website KOMPAS,CNBC
```

Registration (the two battery settings matter for the same reason they do for OPS-01 — this is a laptop, and Task Scheduler silently skips a battery run without marking it "missed", so `-StartWhenAvailable` never queues a catch-up):

```powershell
schtasks /Create /TN "NewsAggregator Scheduled Crawl (morning)" /SC DAILY /ST 07:00 ^
    /TR "<repo>\venv\Scripts\python.exe <repo>\scripts\run_scheduled_crawl.py" /RU "<user>"
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Set-ScheduledTask -TaskName "NewsAggregator Scheduled Crawl (morning)" -Settings $s
```

### Crawler health check (OPS-01)

Registered as a Task Scheduler job named **"NewsAggregator Crawler Health Check"**, daily at 05:30 (`schtasks /Query /TN "NewsAggregator Crawler Health Check" /FO LIST /V` to inspect). It runs `scripts/run_scheduled_health_check.py`, which:
1. Checks how long it's been since the last logged `task='health_check'` `crawl_log` row; if that gap exceeds 36h, sends a distinct Telegram alert flagging that the scheduled job itself may not be firing (OPS-01, #9, reopened 2026-09-17 — see "Detect a scheduler outage" below).
2. Runs `scripts/check_crawlers.py --json --log-db` (exit 0 = all healthy, 1 = one or more BROKEN/PARTIAL/ERROR; also appends a `crawl_log` row per outlet — `started_at`/`finished_at` are that outlet's own check window (OPS-12) — and writes the dated JSON report to `crawler_health/`). `--log-db` implies `--diff-db`: before writing, it reads each outlet's most recent prior `health_check` row and classifies it as `new` (was OK, now needs attention — including OK→FALLBACK), `changed` (e.g. BROKEN→FALLBACK), `recovered`, `unchanged`, or `baseline` (no prior row). The comparison is per outlet, not per batch, so a manual `--website X --log-db` only moves X's baseline.
**Health statuses** (`scripts/check_crawlers.py`): `OK` · `FALLBACK` (listing and extraction work, but every sample was rescued by trafilatura/newspaper — the site's own selector is dead; needs attention, non-fatal) · **`STALE`** (OPS-17: the listing serves fine and parses, but its newest `news:publication_date`/`lastmod` is older than `HEALTH_STALE_LISTING_DAYS`, default 7 — a sitemap generator that died while still serving its last file. SUARA's 20 regional sitemaps were the case that found this: 200, 150 `<url>` each, every one last updated 2022-10-23. Needs attention, **non-fatal**, so it does not affect the exit code; OPS-13's delta reports a listing going stale as `CHANGED`. A listing whose entries carry no dates at all is *not* stale — that is SYS-32's lastmod-only shape) · `PARTIAL` (listing OK, no sample produced text) · **`REPEATED`** (SRC-54: samples produced text, but at least one body repeats itself -- each paragraph a suffix of the one before, the nested-`<p>` cascade that stored all 935 of EMITENNEWS's first articles 3-5x over. Unhealthy: exit 1) · `BROKEN` (listing failed — the note now names the reason: `sitemap fetch failed: HTTP 403` / `HTTP 404` / `SSLError after 5 retries` / `soft-404: …`, so three different tickets stop sharing one message) · `ERROR`.

**Partial runs do not overwrite the day's report** (OPS-10): a full run owns `crawler_health/<date>.json`; any `--website X` run writes `crawler_health/<date>-<websites>.json` and leaves the scheduled report intact. Before this, a one-outlet spot check replaced the 32-outlet report, and that JSON is the only place `avg_chars`, `extractors`, `dto_count` and `note` are kept per outlet.

3. Sends a Telegram notification via `scripts/notify_telegram.py` when the exit code is 1 **or** the delta shows any movement (so a recovery on an all-green day is visible without opening `crawl_log`). The message is the `summary` from the JSON payload and leads with the delta, e.g. `Crawler health 2026-09-18: 🔴 NEW: KOMPAS (BROKEN, was OK) · 🟢 RECOVERED: TEMPO (OK, was ERROR) · unchanged: 16 known (10 BROKEN, 6 FALLBACK)` then a `Totals:` line; on a no-change day the first line is `no change since <previous run, WIB> — 17 known (10 BROKEN, 1 ERROR, 6 FALLBACK)`. `HEALTH_ALERT_ON_NO_CHANGE=false` in `.env` mutes the no-change red days only (OPS-13).
4. Exits with `check_crawlers.py`'s own code, so the task's "Last Run Result" in Task Scheduler reflects the real outcome independent of whether the notification succeeded.

To verify a scraper fix against the baseline without disturbing it: `venv\Scripts\python.exe scripts\check_crawlers.py --website KOMPAS --diff-db --report-dir <somewhere else>` — no `--log-db`, so no row is written, but the summary still says `RECOVERED: KOMPAS (OK, was BROKEN)`. Note that a one-off flap is reported as NEW on the day it happens and RECOVERED the next (observed 2026-09-18: IDXCHANNEL `BROKEN: first branch scraped 0 article links` after 21 s under 8-way concurrency, OK again 1.6 s later); there is deliberately no multi-run suppression — a same-day `--website X --diff-db` re-check settles it.

**Telegram setup** (notifications are silently skipped, logged only, until this is done):
1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts — gives a bot token.
2. Message your new bot anything so it has a conversation with you.
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, find `"chat":{"id": ...}` — that's your chat ID.
4. Add to `.env`: `TELEGRAM_BOT_TOKEN=...` and `TELEGRAM_CHAT_ID=...`.
5. Test with `venv\Scripts\python.exe scripts\notify_telegram.py "test message"`.

**Task settings** (fixed 2026-09-17, OPS-01 reopened twice): the task has `-StartWhenAvailable` and `-WakeToRun` set, so a 05:30 window missed because the machine was off or asleep runs late on next boot/wake instead of being skipped outright for the day (`ExecutionTimeLimit` 2h). Without these, a missed window produced no alert, no exit code, no `crawl_log` row and no JSON report — indistinguishable from a healthy run. The machine is also a laptop, and Task Scheduler's own defaults (`DisallowStartIfOnBatteries=True`, `StopIfGoingOnBatteries=True`) are untouched by the settings above — on battery, the trigger fires but the AC-power condition fails and the run is silently skipped (not "missed", so `-StartWhenAvailable` never catches it up), or a run in progress is killed mid-way if unplugged during it. `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries` removes both. Verify with:
```powershell
(Get-ScheduledTask -TaskName "NewsAggregator Crawler Health Check").Settings | Select-Object StartWhenAvailable, WakeToRun, ExecutionTimeLimit, DisallowStartIfOnBatteries, StopIfGoingOnBatteries
```
To re-apply after any re-creation of the task:
```powershell
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Set-ScheduledTask -TaskName "NewsAggregator Crawler Health Check" -Settings $s
```
The task still runs under `LogonType=Interactive` (only while the user is logged on) — switching to a `ServiceAccount` logon so it doesn't depend on an interactive session was considered but deferred, since it requires re-registering the task with stored credentials; revisit if the machine starts running unattended for long stretches.

**First unattended run observed 2026-09-18** (OPS-01 closed): Task Scheduler `LastRunTime 05:30:02 WIB`, one `health_check` batch of 32 `crawl_log` rows at 22:32 UTC, Telegram alert received on the device. Two caveats remain: (1) catch-up after a genuinely *missed* window has not been exercised — if `-StartWhenAvailable` does not queue the daily trigger, the next successful run's 36 h gap check (below) fires instead, so a missed day surfaces late rather than silently; (2) the `Microsoft-Windows-TaskScheduler/Operational` event log is disabled on this machine, so `Get-ScheduledTaskInfo`'s `LastRunTime` plus the `crawl_log` batch is the only scheduled-vs-manual evidence — `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true` (admin) turns the history on. Two things that first run exposed were fixed the same day: `health_check` rows written before 2026-09-18 06:14 WIB (`log_id ≤ 308`) carry `started_at = finished_at` = the run's end, so read `finished_at` and ignore their zero durations (OPS-12 #75; rows after that have real per-outlet windows), and the alert now leads with what changed instead of re-listing every known-broken outlet (OPS-13 #76, step 3 above).

To re-create the task from scratch: `schtasks /Delete /TN "NewsAggregator Crawler Health Check" /F` then re-run the `schtasks /Create` command in `scripts/run_scheduled_health_check.py`'s docstring, followed by the `Set-ScheduledTask` settings fix above (the `schtasks /Create` defaults do not include `-StartWhenAvailable`/`-WakeToRun`).

**Detect a scheduler outage without opening Task Scheduler:** `-StartWhenAvailable` only helps if the job runs *at all* eventually — a deleted task, an expired credential, or the machine being off for longer than any catch-up window would still stay completely silent otherwise. `run_scheduled_health_check.py` now checks this itself on every run (step 1 above) and alerts on a >36h gap, but the same gap is also directly queryable — see "Detect a missed/broken schedule" below.

---

## Monitoring & Health Checks

### Check API quota usage
```sql
SELECT log_date, api_name, call_count
FROM api_usage_log
ORDER BY log_date DESC
LIMIT 7;
```
Stop at 1,400 calls/day (hard-coded guard). If limit is hit frequently, reduce `KNOWLEDGE_BATCH_SIZE`.

### Check crawl health
```sql
SELECT website, task, status, article_count, error_msg,
       started_at, finished_at,
       EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_sec
FROM crawl_log
ORDER BY started_at DESC
LIMIT 20;
```
Red flags: `status='failed'`, `article_count=0` for a source that normally produces articles.

### Which outlet is slow, and what changed since the previous health check (OPS-12, OPS-13)
```sql
-- Latest health_check row per outlet with its real check duration (rows from 2026-09-18 06:14 WIB on).
SELECT DISTINCT ON (website) website, split_part(error_msg, ':', 1) AS status,
       ROUND(EXTRACT(EPOCH FROM (finished_at - started_at))::numeric, 1) AS duration_sec, finished_at
FROM crawl_log WHERE task = 'health_check'
ORDER BY website, finished_at DESC, log_id DESC;

-- Status of each outlet in its last two health_check rows; rows where they differ are the delta the alert led with.
WITH ranked AS (
  SELECT website, split_part(error_msg, ':', 1) AS status, finished_at,
         ROW_NUMBER() OVER (PARTITION BY website ORDER BY finished_at DESC, log_id DESC) AS rn
  FROM crawl_log WHERE task = 'health_check')
SELECT a.website, b.status AS previous, a.status AS current, a.finished_at
FROM ranked a JOIN ranked b ON b.website = a.website AND b.rn = 2
WHERE a.rn = 1 AND a.status <> b.status;
```
The 60 s per-outlet budget in `check_crawlers.py` shows up as `ERROR: timeout after 60s` with a ~60–66 s duration (the sequential wait on the futures adds a few seconds); TEMPO's is SRC-06, not a slow site. A `duration_sec` of 0.0–1 s on a `BROKEN: sitemap fetch failed` row is a refused/404 sitemap URL, not a timeout. `started_at` is also the outlet's start, so `MIN(started_at)` of a batch is within a couple of seconds of the process start (Task Scheduler's `LastRunTime` + module import).

### Detect a missed/broken schedule (OPS-01, #9)
```sql
SELECT MAX(finished_at) AS last_health_check,
       EXTRACT(EPOCH FROM (NOW() - MAX(finished_at))) / 3600 AS hours_since
FROM crawl_log
WHERE task = 'health_check';
```
Red flag: `hours_since > 36` (or a NULL `last_health_check`) — the scheduled job (05:30 daily) has stopped firing, from Task Scheduler, credentials, or the machine being off longer than its catch-up window. This is the same query `scripts/run_scheduled_health_check.py` runs on every invocation to alert on a gap by itself, but it's checkable here directly, without opening Task Scheduler — the point being that a broken *notifier* (no Telegram alert) must not also be a silent one.

### Check for a reporter selector that landed on the wrong element (SRC-10)
```sql
SELECT s.sources, COUNT(*) FILTER (WHERE a.writer::text ~ '^\["[0-9]+"\]$') AS numeric_writer, COUNT(*) AS total
FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
GROUP BY 1 HAVING COUNT(*) FILTER (WHERE a.writer::text ~ '^\["[0-9]+"\]$') > 0;
```
A hand-written `_get_reporter_from_text` selector can drift onto a timestamp/id element instead of the byline and still return a non-empty, plausible-looking string -- no "missing byline" check catches that, since the field isn't actually empty. Every crawler's output is now filtered through `Crawler._looks_like_a_name` (drops anything that's purely digits or parses as a date) before it reaches the DTO, so this should stay empty for articles crawled after 2026-09-17. **Known exception:** IDXCHANNEL's own bug (`_get_reporter_from_text` matching the publication-date `<div>` instead of the byline `<a>`) was fixed the same day, but the 615 rows it had already written before the fix were left as-is (recovering the real name needs a live re-fetch per article, not a re-chunk from stored text) -- deliberately deferred, P3, not a regression.

### Check which extractor is actually producing article text (OPS-02)
```sql
SELECT s.sources, a.meta_data->>'extractor' AS extractor, COUNT(*)
FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```
Only populated for articles crawled after OPS-02 landed (2026-09-16) — older rows show `NULL`, since the field wasn't recorded before. A source where every row is `trafilatura`/`newspaper` and none is `site` means the site's own selector is dead even though `check_crawlers.py` may still say `FALLBACK` (or, before this fix, a misleading `OK`) — see `scripts/check_crawlers.py`'s `FALLBACK` status.

### Check digest generation
```sql
SELECT digest_date, cluster_count, article_count, generation_ms, generated_at
FROM newsletter_digests
ORDER BY digest_date DESC
LIMIT 7;
```
If today's digest is missing after 07:30 WIB, run newsletter task manually.

### Check dead-link accumulation (SYS-09)
```sql
SELECT sources, COUNT(*) FILTER (WHERE fetch_failures > 0) AS ever_failed,
       COUNT(*) FILTER (WHERE fetch_failures >= 3) AS excluded_now,
       MAX(fetch_failures) AS worst
FROM sitemaps GROUP BY sources HAVING COUNT(*) FILTER (WHERE fetch_failures > 0) > 0
ORDER BY excluded_now DESC;
```
`fetch_failures` counts runs that produced no `NewsDetailsDTO` for that sitemap (fetch failure, or any exception in `_get_news_details`). Once `fetch_failures >= SITEMAP_MAX_FETCH_FAILURES` (env var, default 3), `load_all_sitemaps` excludes the row instead of re-fetching a dead URL on every run forever. A high `excluded_now` for one source usually means a dead sitemap section or a source that needs SRC-02/03/04-style attention, not that its content ran out.

Since OPS-15 (#81) `last_fetch_error` is the real reason per row -- `HTTP 404`, `HTTP 403`, `ReadTimeout after 5 retries`, `ConnectionError after 5 retries`, `soft-404: redirected to …`, `soft-404: canonical …`, `HTML parse failed: …`, or the exception type raised inside the extractor -- so this tells a dead link from a block from a crash:
```sql
SELECT sources, last_fetch_error, COUNT(*) FROM sitemaps
WHERE fetch_failures > 0 GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;
```
Rows written before 2026-09-18 all carry the old constant `fetch or extraction produced no result` (none existed on that date -- `fetch_failures` was 0 everywhere).

**A source-wide failure spares the source-level reasons, not the dead URLs** (OPS-15, reworked by OPS-16 on 2026-09-25). A run is source-wide only when **both** hold: at least `SITEMAP_SOURCE_FAILURE_RATIO` (default `1.0`, every one) of its attempted sitemaps failed, **and** at least `SITEMAP_SOURCE_FAILURE_MIN` (default `20`) failed. Below the floor, 3 of 3 failing is 3 dead URLs, not an outage. They are counted individually with a WARNING naming the floor (BISNIS's shape: a 3-row queue, 403-blocked). In a source-wide run, `_record_fetch_failures`:
- **counts the per-URL reasons anyway**: `HTTP 404`, `HTTP 410` and `soft-404` (`PER_URL_FAILURE_MARKERS`) are facts about the URL, true whether 3 or 1,000 came back that way. They bump `fetch_failures` as usual, so a dead window still retires after `SITEMAP_MAX_FETCH_FAILURES` runs.
- **spares the source-level reasons** (403, 5xx, connection/TLS/DNS errors, timeouts, extractor regressions). They are not counted, but their `last_crawl_attempt` **is stamped**, so they sit out the normal `SITEMAP_RECRAWL_COOLDOWN_DAYS` (7) cooldown instead of being re-fetched on the very next run, and a dead newest-1,000 window rotates out of `load_all_sitemaps`' `LIMIT 1000`.
- **logs at ERROR and persists the verdict** in that run's `crawl_log.error_msg` (`status='completed'`), e.g. `source-wide fetch failure: 40/40 (100%); 0 counted as per-URL, 40 spared and cooldown-stamped. Reasons: 'HTTP 403': 40`. It is queryable from the DB, not only on stderr: see **"Was the last run a source-wide fetch failure?"** under the next heading.

Between 50% and the ratio the run logs a WARNING and counts everything individually. **Residual risk, accepted 2026-09-25:** because 404s count even when *every* URL fails, a crawler-side change that makes a whole source 404 (a bad `_get_link` rewrite, say) retires up to 1,000 rows per run for `SITEMAP_MAX_FETCH_FAILURES` runs. That is exactly what OPS-15 was written to prevent. The ERROR line and the persisted verdict make it visible, and `scripts/reset_fetch_failures.py --website X` undoes it. After a crawler change, read the next run's verdict before the third run.

**Bring retired sitemaps back** with `scripts/reset_fetch_failures.py` (always `--dry-run` first), after fixing whatever caused the failures:
```powershell
venv\Scripts\python.exe scripts\reset_fetch_failures.py --dry-run --website KOMPAS
venv\Scripts\python.exe scripts\reset_fetch_failures.py --website KOMPAS              # every failed row of one source
venv\Scripts\python.exe scripts\reset_fetch_failures.py --all-retired                 # only rows at/above the cap, all sources
venv\Scripts\python.exe scripts\reset_fetch_failures.py --like "HTTP 403%"            # one failure mode
venv\Scripts\python.exe scripts\reset_fetch_failures.py --sitemap-ids 123,456 --clear-cooldown
```
Resets `fetch_failures` to 0 and clears `last_fetch_error`. A reset row still waits out its cooldown (the failure stamped `last_crawl_attempt`); `--clear-cooldown` also nulls that so it is eligible on the very next run. Nothing else does this automatically -- retirement is otherwise permanent.

### Check sitemap terminal-state distribution (SYS-16)
```sql
SELECT crawl_status, COUNT(*) AS sitemaps,
       COUNT(*) FILTER (WHERE last_crawl_attempt < NOW() - INTERVAL '7 days') AS past_cooldown
FROM sitemaps
GROUP BY crawl_status
ORDER BY sitemaps DESC;
```
**Was the last run a source-wide fetch failure?** (OPS-16) A run in which the source itself was down used to be indistinguishable in `crawl_log` from a run that fetched everything and filtered it all out — both `status='completed', article_count=0, error_msg=NULL` — and `logging.basicConfig()` has no file handler, so under Task Scheduler the ERROR line was gone too. The verdict is now persisted on the row:

```sql
SELECT website, started_at, article_count, error_msg
FROM crawl_log
WHERE task = 'full_text' AND error_msg LIKE 'source-wide fetch failure%'
ORDER BY started_at DESC
LIMIT 20;
```
The message carries the counts and the reason breakdown, e.g. `source-wide fetch failure: 40/40 (100%); 0 counted as per-URL, 40 spared and cooldown-stamped. Reasons: 'HTTP 403': 40`. A 404/soft-404 is a fact about the URL, so it is still counted toward `SITEMAP_MAX_FETCH_FAILURES` even at 100% — only source-level reasons (403, 5xx, connection, TLS, timeouts, extractor regressions) are spared, and those rows get `last_crawl_attempt` stamped so the window rotates out of `load_all_sitemaps`' `ORDER BY posted_at DESC LIMIT 1000`.

**No `crawl_log` row for a run that should have happened?** Since OPS-07 that is stated explicitly rather than inferred. A failure to *write* `crawl_log` used to be logged at DEBUG — below the INFO level the pipeline runs at — so a missing table, a column drift, a brief DB outage or a permission change left no row and no message, and the runbook read that as "the scheduler did not fire". The writers still never raise (a logging failure must not abort a crawl), but they log at WARNING now, and the first failure emits `crawl_log disabled for this run: <reason> -- this run will leave NO crawl_log row, which is not the same as the scheduler failing to fire (OPS-07)` once at the top of the log. So: if there is no row, check the run's log for that line before concluding the task never started.

`rejected_filter` rows are excluded from `load_all_sitemaps` permanently (off-topic, will fail the same semantic filter again) — a large and growing `pending`+`past_cooldown` count for a source that keeps producing few articles usually means its extractor is broken (`empty_extraction`), not that it has nothing to say; check `scripts/check_crawlers.py --website <NAME>` before assuming the source has gone quiet. If `SOFT_THRESHOLD` moves, or the probe artifact in `newscrawler/core/models/` is retrained, re-run `scripts/backfill_sitemap_crawl_status.py` to reclassify — `rejected_filter` is a one-time decision, not re-evaluated automatically. (`INTERESTS` and the 0.35 cosine threshold no longer exist; SYS-37 replaced them on 2026-09-22.)

**The category gate is symmetric since SYS-35 (#118), 2026-09-20:** `category_gate()` in `newscrawler/core/importance_filter.py` is the one decision -- a soft vertical (`OFFTOPIC_CATEGORIES_EXACT`/substring/word lists) is rejected before the score, a news desk (`NEWS_CATEGORIES`: `bisnis`/`ekonomi`/`nasional`/`politik`/`hukum`/`kriminal`/...) is kept before the score, and only a mixed bucket (`news`, `berita`, regional subdomains, a name neither list knows) is scored. `kriminal` and `edukasi` are news now; IDNTIMES's `life`/`hype`/`korea`/`fiction`/`men`/`food` and the other soft names sampled on 2026-09-20 are denied (SYS-34, #115). Every `task=full_text` run logs `filter decisions this run: allow=… deny=… score=… empty=…` and, per news category, the semantic score's own recall (`semantic-score recall on news categories … bisnis=62/100 (62%)`) -- ~50% is expected until SYS-37 replaces the score. A `WARNING … first article ever saved under category 'X' (never seen before on this source)` means a new vocabulary reached the save path: sample its titles and put it on the deny-list or the allow-set. Two one-off repairs, both `--dry-run` first: `scripts/requeue_finance_rejects.py` flips finance-section `rejected_filter` rows back to `pending` (and clears the cooldown) so the next `task=full_text` re-fetches them; `scripts/fix_url_shaped_categories.py --website CNN,JPNN` rewrites URL-shaped `sitemaps.category` values to the section name through each crawler's `branch_name_from_url()` (SRC-36/SRC-41). `scripts/repair_placeholder_headlines.py` (SYS-33, #114) replaces TIRTO/TEMPO URL-slug headlines with the page's `og:title`.

**`rejected_filter` can be wrong when a sitemap already has FAISS evidence (DBT-20, #70):** `backfill_sitemap_crawl_status.py` approximates the classification from a fresh headline-only re-check, not a re-run of the original filter -- for 582 MEDIAINDONESIA sitemaps (2026-09-18) that approximation disagreed with direct evidence (a real L1 vector already existed, meaning the original filter passed). `scripts/fix_rejected_filter_with_faiss_evidence.py [--website NAME] [--dry-run]` finds and corrects any `rejected_filter` row whose `sitemap_id` has an L1 FAISS vector, flipping it back to `pending`. Safe to re-run any time; reports "Nothing to fix" once clean. That alone does **not** get the article crawled: a `pending` row re-enters `load_all_sitemaps`' `ORDER BY posted_at DESC LIMIT 1000` queue behind everything newer for that source (12,000+ rows for MEDIAINDONESIA), and nothing is scheduled to drain it. `scripts/recrawl_faiss_orphans.py --website NAME [--dry-run] [--limit N]` does the re-crawl directly: it selects every sitemap that has an L1 vector but no `chunks`/`articles` row and hands exactly those to `crawl_newsdetails(specific_sitemaps=...)`, so they go through the normal fetch → filter → chunk → save path (the existing L1 vector is reused, SYS-17) regardless of queue position. It reports what the targets became afterwards; a target the filter now rejects, or whose page is gone, keeps its orphan L1 vector -- write those off separately. DBT-26 (#85) tracks stopping `backfill_sitemap_crawl_status.py` from misclassifying evidenced rows in the first place.

### Check articles/chunks divergence (SYS-17, OPS-04)
```sql
SELECT COUNT(*) AS orphan_articles
FROM articles a
WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id);

SELECT COUNT(*) AS pending_embedding_chunks, COUNT(DISTINCT sitemap_id) AS affected_sitemaps
FROM chunks WHERE embedding_id IS NULL;
-- DBT-23 (#74): rows with no vector id. Since 2026-09-22 the pipeline repairs them itself on the
-- sitemap's next save (the level is offered again and save_chunks upserts in place); a count that
-- stays > 0 across runs means the sitemap is never re-offered -- scripts/backfill_pending_embeddings.py.
SELECT COUNT(*) AS unembedded_chunks FROM chunks WHERE embedding_id IS NULL;
```
`orphan_articles` should be 0 -- an `articles` row with no `chunks` row means `save_chunk_data`'s SQL insert never landed even though the article was saved (SYS-17's exact bug: FAISS had the vectors, `chunks` did not). If nonzero, `scripts/backfill_orphan_chunks.py` repairs it by re-chunking from `articles.extracted_text` (no re-crawl needed) and reuses whatever FAISS already has. `pending_embedding_chunks` nonzero is the opposite direction (DBT-17, still open) -- a `chunks` row that was inserted but never actually embedded into FAISS.

### Check full FAISS/chunks/articles consistency (OPS-04)
```powershell
venv\Scripts\python.exe scripts\check_store_consistency.py            # table + JSON report
venv\Scripts\python.exe scripts\check_store_consistency.py --quiet    # one-line summary, for cron
```
The SQL-only queries above catch two of nine checks (`orphan_articles`, `pending_embedding_chunks`); this script also loads both `NEWS_L1`/`NEWS_L2` FAISS docstores directly via `pickle` (no embedding model, seconds not minutes) and cross-references sitemap_ids against `articles`/`chunks`, so it catches the divergences neither store alone can see -- e.g. a FAISS vector with no `articles` row at all, or a sitemap in L1 but not L2. Status per check is `OK` (zero), `KNOWN` (nonzero but at or below its `BASELINE` entry, i.e. ticketed debris) or `GROWING` (above it: investigate). **Since 2026-09-26 every baseline is 0** (OPS-25 #174). A baseline above the real count hides that much new damage: the 1,237 terminal VIVA orphans read `6529 6529 KNOWN`. A vector with no article is split by what can still happen to its sitemap, using the repair's own classification. `terminal sitemap_ids in L1/L2 FAISS (no article)` is a check with baseline 0: the sitemap can never get an article, so RAG serves a hit with nothing behind it. `queued sitemap_ids … (link up later)` is information only: the crawl links those up when it reaches them. Exit code 1 if any check is nonzero. Since OPS-29 the scheduled crawl runs this check after every run (see "Scheduled crawl"). `/api/health`'s `faiss_docs` field (`{"NEWS_L1": n, "NEWS_L2": n}`) surfaces the same totals in the web UI, read from each `index.faiss` header (`faiss.read_index(..., IO_FLAG_MMAP).ntotal`, ~60 ms cold) and cached on the file's `(mtime, size)`, so polling it is free until the pipeline writes a new index; the whole payload runs in the threadpool (OPS-14 -- the first version unpickled both docstores per request, 2 s and 300 MB on the event loop). Not yet on the Task Scheduler/Telegram path OPS-01 uses -- run manually until that's wired up.

**Repair (OPS-04):** `venv\Scripts\python.exe scripts\repair_store_consistency.py` (dry run) then `--apply`. Three idempotent actions. (1) A sitemap with no article that can never get one (`rejected_filter`, fetch cap, row gone) loses its vectors **and** its chunk rows together. (2) A vector whose sitemap has an article but no chunk row gets the row rebuilt from the docstore. (3) Duplicate vectors per (sitemap, level, index) are cut to the one a chunk row points at. Still-queued sitemaps are left alone: they link up when crawled (reported as `healing`). `--apply` copies both indexes to `backups/faiss_<stamp>/` (plus deleted chunk rows as JSON). It refuses (exit 2) while the scheduled crawl holds its run lock (OPS-26) or any crawl has a `started` row, since a running crawl flushes its in-memory index and would undo the repair (DBT-10). Run `check_store_consistency.py` afterwards: `chunks sitemap_ids not in FAISS` must stay 0.

**The crawl cleans up what it settles itself (SYS-54, #185).** At the end of each source's `full_text`, every sitemap the run settled for good (rejected by category or by the probe, or a fetch failure that reached `SITEMAP_MAX_FETCH_FAILURES`) and that has no article loses its vectors and chunk rows: the vectors leave the in-memory indexes and are flushed with the source's own adds, and the chunk rows are deleted only after that flush succeeded (the repair's order). The log says `<SOURCE>: removed N vector(s) of sitemaps settled terminal this run (SYS-54)`. So the 5,292 queued VIVA sitemaps with June-era vectors no longer turn into `terminal … GROWING` when the crawl rejects them. A failure of this step is logged at ERROR and leaves the orphans for the check and the repair below.

**After any script that moves rows to `rejected_filter`, run the check, then the repair** (OPS-25). That covers `reject_denied_categories.py`, `cleanup_soft_by_probe.py`, and the SRC-33/SRC-29 retirement scripts. A sitemap that was queued *with vectors* becomes terminal, so its vectors and chunk rows are orphans from that moment. That is how SRC-33's 06:30 retirement left 1,237 VIVA orphans after OPS-04's 01:23 repair. The checker now shows it as `terminal … GROWING` the same day.

### Check chunk-level completeness (SYS-25)
```sql
SELECT COUNT(*) FILTER (WHERE l1 = 0) AS no_l1, COUNT(*) FILTER (WHERE l2 = 0) AS no_l2
FROM (
    SELECT sitemap_id,
           COUNT(*) FILTER (WHERE chunk_level = 1) AS l1,
           COUNT(*) FILTER (WHERE chunk_level = 2) AS l2
    FROM chunks GROUP BY 1
) t;
```
Both should be 0 -- `orphan_articles` above only catches a sitemap with *zero* chunks rows; a sitemap with chunks at one level and missing the other used to be invisible to both the dedup logic and `backfill_orphan_chunks.py` (fixed alongside this query). `no_l1 > 0` means `_enrich_with_parent_context` finds no parent row for those sitemaps' L2 chunks, so RAG answers citing them lose their title/link. Repair the same way: `scripts/backfill_orphan_chunks.py` now selects "missing L1 OR missing L2", and `save_chunk_data`'s dedup is keyed on `(sitemap_id, chunk_level)` so re-chunking only inserts the level that's actually missing.

### Check migration status (OPS-05)
```sql
SELECT name, applied_at FROM schema_migrations ORDER BY applied_at;
```
Compare the row count against `scripts/migrate.py`'s `MIGRATIONS` list -- `tests/integration/test_schema.py::TestSchemaMigrationsTracksEveryFile` fails the suite if any known migration file has no row here. If a new `migrate_*.sql` file is added, add it to both `MIGRATIONS` and CLAUDE.md's documented order, then run `python scripts/migrate.py`.

### Check for duplicate article rows (DBT-07)
```sql
SELECT COUNT(*) - COUNT(DISTINCT sitemap_id) AS duplicate_rows FROM articles;
```
Should be 0 — `articles_sitemap_id_uq` (see `scripts/migrate_articles_unique_sitemap.sql`) prevents new duplicates; a nonzero count means the unique index is missing or was dropped.

### Check for duplicate chunk rows (DBT-09)
```sql
SELECT COUNT(*) FROM (
    SELECT 1 FROM chunks GROUP BY sitemap_id, chunk_level, chunk_index HAVING COUNT(*) > 1
) t;
```
Should be 0 — `chunks_sitemap_level_index_uq` (see `scripts/migrate_chunks_unique.sql`) prevents new duplicates, and `ChunkFAISSDatasource._embed_batch` dedups within an incoming batch before embedding. A nonzero count means either the index was dropped or a duplicate was inserted through a path that bypasses `_embed_batch`; repair with `scripts/dedupe_chunks.py` (dry-run first — it also deletes the loser's now-orphaned FAISS vector).

### Check for duplicate sitemap rows (SYS-29)
```sql
SELECT COUNT(*) FROM (SELECT 1 FROM sitemaps GROUP BY link HAVING COUNT(*) > 1) t;
```
Should be 0 — `sitemaps_link_uq` (see `scripts/migrate_sitemaps_unique_link.sql`) makes the link the identity of a sitemap row, and `save_sitemaps` dedups on the same key (link alone — **not** `(link, posted_at)`; the date was never part of a URL's identity, and keying on it let SYS-11's +1-day WIB correction and OKEZONE-style `news:publication_date` re-stamps (OKEZONE's is its sitemap's render time on every branch; since SRC-51 its date comes from the URL) each insert a second row → second `articles` row → duplicate chunks/FAISS vectors). A re-listed link whose `posted_at` moved is recognised and left as first seen; the stored date is not refreshed. A nonzero count means the index was dropped; repair with `scripts/dedupe_sitemap_links.py` (dry-run first — it also removes the losers' `articles`/`chunks` rows and FAISS vectors, backing everything up to `backups/`). Before any `task=sitemap`/`task=all` after a change to how `posted_at` or `link` is derived, run `scripts/experiments/probe_sitemap_dedup_drift.py` (network, read-only): it fetches each HEALTHY source's live sitemap and asks the real `find_existing_by_link` lookup which links it would insert — `would_insert_duplicate` must be 0 everywhere; `date_drift` is informational.

### Check entity extraction progress (OPS-09)
```sql
SELECT
  COUNT(*) FILTER (WHERE knowledge_extracted = 1) AS extracted,
  COUNT(*) FILTER (WHERE knowledge_extracted = 0 AND knowledge_extract_attempts < 3) AS pending_retryable,
  COUNT(*) FILTER (WHERE knowledge_extracted = 0 AND knowledge_extract_attempts >= 3) AS retired
FROM articles;
```
`retired` counts articles `get_articles_pending_extraction` will never select again (SYS-19's attempt cap, default `KNOWLEDGE_EXTRACT_MAX_ATTEMPTS=3`). Plain `knowledge_extracted = 0` (the old query) conflates `pending_retryable` and `retired` -- a growing `retired` count with `pending_retryable` flat is the retirement mechanism doing its job on genuinely bad articles; a `retired` count that jumped in one run is more likely an API-side incident. Since OPS-09's fix, only a response Gemini actually returned but couldn't be used (safety block, unparseable JSON) counts an attempt -- a network/timeout/5xx/rate-limit/auth failure (`GeminiTransientError`) never does, so an API outage no longer inflates `retired` on its own. **Since OPS-11 (#67) that outage is visible where it belongs:** `task=extract_knowledge` and `task=newsletter` write a `crawl_log` row under `website='ALL'`, and a run in which *every* Gemini call failed without a response is `status='failed'` with `error_msg='all N Gemini calls failed without a response: <first error>'`. Check it before reading the counts above:

```sql
SELECT task, status, started_at, article_count, left(error_msg, 120) AS error
FROM crawl_log WHERE task IN ('extract_knowledge', 'newsletter') ORDER BY log_id DESC LIMIT 5;
```

No row for today = the task did not run (scheduling); `failed` with `all N Gemini calls failed` = the key/model/quota (OPS-20); `completed` with `article_count=0` and `pending_retryable > 0` = the daily cap or the window.

See what's actually failing:
```sql
SELECT last_extract_error, COUNT(*)
FROM articles
WHERE knowledge_extracted = 0 AND knowledge_extract_attempts > 0
GROUP BY last_extract_error
ORDER BY 2 DESC
LIMIT 20;
```

**Bring retired articles back** with `scripts/reset_extraction_attempts.py` (always `--dry-run` first):
```powershell
venv\Scripts\python.exe scripts\reset_extraction_attempts.py --dry-run --all-retired
venv\Scripts\python.exe scripts\reset_extraction_attempts.py --all-retired
venv\Scripts\python.exe scripts\reset_extraction_attempts.py --like "%503%"          # only a specific failure mode
venv\Scripts\python.exe scripts\reset_extraction_attempts.py --sitemap-ids 123,456   # specific articles
```
Resets `knowledge_extract_attempts` to 0 and clears `last_extract_error`, re-entering the article into `get_articles_pending_extraction`'s queue. Nothing else does this automatically -- retirement is otherwise permanent.

### API stats endpoint
```
GET http://localhost:8000/api/stats
GET http://localhost:8000/api/health
```

---

## One-Time Setup (first run)

```bash
# 1. Run migrations (OPS-05: applies every scripts/migrate_*.sql the DB doesn't
#    already have, in CLAUDE.md's documented order, and records each one in a
#    schema_migrations table so a second run is a no-op)
python scripts/migrate.py

# 2. Set GEMINI_API_KEY
export GEMINI_API_KEY=your_key_here

# 3. Seed entity aliases
python scripts/seed_entity_aliases.py

# 4. Run initial crawl
python -c "
from newscrawler.application.api.lambda_function import lambda_handler
lambda_handler.process_event({'task': 'all', 'website': 'BISNIS,KOMPAS,CNBC,KONTAN,DETIK'}, None)
"

# 5. Run extraction + newsletter
python -c "
from newscrawler.application.api.lambda_function import lambda_handler
lambda_handler.process_event({'task': 'extract_knowledge'}, None)
lambda_handler.process_event({'task': 'newsletter'}, None)
"
```

---

## Troubleshooting

**FAISS index corrupt or won't load** (DBT-10 #45)
- Every save is atomic: written to `NEWS_L*.tmp`, then swapped in with `os.replace`, pkl before faiss. The previous generation is kept as `index.faiss.bak`/`index.pkl.bak`. A crash can leave a stale-but-consistent pair, not a mismatched one.
- To roll back one generation, with no crawl running: `cd NEWS_L1; copy index.faiss.bak index.faiss; copy index.pkl.bak index.pkl` (same for `NEWS_L2`). Then `venv\Scripts\python.exe scripts\check_store_consistency.py`.
- Older copies: `backups/faiss_*/` (taken before risky operations, e.g. the OPS-23 migration). A full rebuild from SQL is `scripts/backfill_orphan_chunks.py` (re-chunks from `articles.extracted_text`), which is slow.
- Since DBT-10 the crawl saves each index **once per source** (in `deferred_embeddings`), not once per batch. Chunk rows are written with `embedding_id` NULL / `pending_embedding` until that save has succeeded. A run killed mid-source (OPS-22's timeout) therefore leaves NULL rows, never rows pointing at vectors that were not saved. The source's next article crawl re-embeds them before it starts. To check: `SELECT count(*) FROM chunks WHERE embedding_id IS NULL` is 0 between runs. To repair outside a crawl: `scripts/backfill_pending_embeddings.py`.

**FAISS index not found on startup**
- First run creates empty indexes automatically. Run a crawl to populate them.

**`google.generativeai` not installed**
```bash
pip install google-generativeai
```

**`fastapi`/`uvicorn` not installed**
```bash
pip install fastapi uvicorn jinja2 python-multipart
```

**`scikit-learn` not installed (needed for DBSCAN)**
```bash
pip install scikit-learn
```

**Newsletter: 0 clusters produced**
- Check `DBSCAN_EPS` — try raising to 0.35 if articles are too dissimilar.
- Check that today's articles exist: `SELECT COUNT(*) FROM sitemaps WHERE posted_at = YYYYMMDD;`

**RAG: FTS returns no results**
- Ensure `migrate_phase4.sql` has been run (adds `fts_vector` generated column).
- Check: `SELECT COUNT(*) FROM chunks WHERE fts_vector IS NOT NULL;`
