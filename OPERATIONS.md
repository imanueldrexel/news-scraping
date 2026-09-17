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
| `DAILY_API_CALL_LIMIT` | `1400` | Hard stop for Gemini calls/day |
| `KNOWLEDGE_BATCH_SIZE` | `50` | Articles per extraction run |
| `EMBEDDING_MODEL_HF` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model |
| `VECTOR_DB_NAME_L1` | `NEWS_L1` | FAISS L1 index directory |
| `VECTOR_DB_NAME_L2` | `NEWS_L2` | FAISS L2 index directory |
| `DIGESTS_DIR` | `digests` | Newsletter output directory |
| `DBSCAN_EPS` | `0.25` | Cluster similarity threshold |
| `DBSCAN_MIN_SAMPLES` | `2` | Min articles per cluster |
| `RAG_TOP_K` | `5` | Chunks used for RAG answer |

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

## Recommended Schedule (Windows Task Scheduler)

| Time (WIB) | Task | Command |
|---|---|---|
| 05:30 | Crawler health check (OPS-01) | `scripts/run_scheduled_health_check.py` — registered, see below |
| 06:00 | Morning crawl | `python __main__.py` (task=all) |
| 06:45 | Knowledge extraction | task=extract_knowledge |
| 07:00 | Newsletter | task=newsletter |
| 18:00 | Evening crawl | task=all |
| 18:45 | Knowledge extraction | task=extract_knowledge |

### Crawler health check (OPS-01)

Registered as a Task Scheduler job named **"NewsAggregator Crawler Health Check"**, daily at 05:30 (`schtasks /Query /TN "NewsAggregator Crawler Health Check" /FO LIST /V` to inspect). It runs `scripts/run_scheduled_health_check.py`, which:
1. Checks how long it's been since the last logged `task='health_check'` `crawl_log` row; if that gap exceeds 36h, sends a distinct Telegram alert flagging that the scheduled job itself may not be firing (OPS-01, #9, reopened 2026-09-17 — see "Detect a scheduler outage" below).
2. Runs `scripts/check_crawlers.py --quiet --log-db` (exit 0 = all healthy, 1 = one or more BROKEN/PARTIAL/ERROR; also appends a `crawl_log` row per outlet and writes the dated JSON report to `crawler_health/`).
3. On exit 1, sends a Telegram notification with the one-line summary via `scripts/notify_telegram.py`.
4. Exits with `check_crawlers.py`'s own code, so the task's "Last Run Result" in Task Scheduler reflects the real outcome independent of whether the notification succeeded.

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

**First unattended run observed 2026-09-18** (OPS-01 closed): Task Scheduler `LastRunTime 05:30:02 WIB`, one `health_check` batch of 32 `crawl_log` rows at 22:32 UTC, Telegram alert received on the device. Two caveats remain: (1) catch-up after a genuinely *missed* window has not been exercised — if `-StartWhenAvailable` does not queue the daily trigger, the next successful run's 36 h gap check (below) fires instead, so a missed day surfaces late rather than silently; (2) the `Microsoft-Windows-TaskScheduler/Operational` event log is disabled on this machine, so `Get-ScheduledTaskInfo`'s `LastRunTime` plus the `crawl_log` batch is the only scheduled-vs-manual evidence — `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true` (admin) turns the history on. Note also that `health_check` rows currently carry `started_at = finished_at` (the run's end, OPS-12 #75), and that the alert lists every known-broken outlet every day with no new-vs-known distinction (OPS-13 #76).

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

### Check sitemap terminal-state distribution (SYS-16)
```sql
SELECT crawl_status, COUNT(*) AS sitemaps,
       COUNT(*) FILTER (WHERE last_crawl_attempt < NOW() - INTERVAL '7 days') AS past_cooldown
FROM sitemaps
GROUP BY crawl_status
ORDER BY sitemaps DESC;
```
`rejected_filter` rows are excluded from `load_all_sitemaps` permanently (off-topic, will fail the same semantic filter again) — a large and growing `pending`+`past_cooldown` count for a source that keeps producing few articles usually means its extractor is broken (`empty_extraction`), not that it has nothing to say; check `scripts/check_crawlers.py --website <NAME>` before assuming the source has gone quiet. If `INTERESTS` or the filter threshold changes, re-run `scripts/backfill_sitemap_crawl_status.py` to reclassify — `rejected_filter` is a one-time decision, not re-evaluated automatically.

### Check articles/chunks divergence (SYS-17, OPS-04)
```sql
SELECT COUNT(*) AS orphan_articles
FROM articles a
WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id);

SELECT COUNT(*) AS pending_embedding_chunks, COUNT(DISTINCT sitemap_id) AS affected_sitemaps
FROM chunks WHERE embedding_id IS NULL;
```
`orphan_articles` should be 0 -- an `articles` row with no `chunks` row means `save_chunk_data`'s SQL insert never landed even though the article was saved (SYS-17's exact bug: FAISS had the vectors, `chunks` did not). If nonzero, `scripts/backfill_orphan_chunks.py` repairs it by re-chunking from `articles.extracted_text` (no re-crawl needed) and reuses whatever FAISS already has. `pending_embedding_chunks` nonzero is the opposite direction (DBT-17, still open) -- a `chunks` row that was inserted but never actually embedded into FAISS.

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

### Check entity extraction progress (OPS-09)
```sql
SELECT
  COUNT(*) FILTER (WHERE knowledge_extracted = 1) AS extracted,
  COUNT(*) FILTER (WHERE knowledge_extracted = 0 AND knowledge_extract_attempts < 3) AS pending_retryable,
  COUNT(*) FILTER (WHERE knowledge_extracted = 0 AND knowledge_extract_attempts >= 3) AS retired
FROM articles;
```
`retired` counts articles `get_articles_pending_extraction` will never select again (SYS-19's attempt cap, default `KNOWLEDGE_EXTRACT_MAX_ATTEMPTS=3`). Plain `knowledge_extracted = 0` (the old query) conflates `pending_retryable` and `retired` -- a growing `retired` count with `pending_retryable` flat is the retirement mechanism doing its job on genuinely bad articles; a `retired` count that jumped in one run is more likely an API-side incident. Since OPS-09's fix, only a response Gemini actually returned but couldn't be used (safety block, unparseable JSON) counts an attempt -- a network/timeout/5xx/rate-limit/auth failure (`GeminiTransientError`) never does, so an API outage no longer inflates `retired` on its own.

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
