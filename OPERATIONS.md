# NewsAggregator — Operations Guide

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_DB_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_DB_PORT` | `5431` | PostgreSQL port |
| `POSTGRES_DB_USER` | `postgres` | DB user |
| `POSTGRES_DB_PASS` | `postgres` | DB password |
| `POSTGRES_DB_NAME` | `newsaggregator` | DB name |
| `GEMINI_API_KEY` | — | Gemini key: extraction and the newsletter when their provider is `gemini`; the search page only when `RAG_LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model name |
| `GEMINI_DAILY_CALL_LIMIT` | `20` | OPS-20 (#136): Gemini calls/day per model, counted in `api_usage_log`. **This project's free tier enforces 20/day/model**; knowledge extraction stops cleanly at the limit instead of spinning on 429s, and logs one WARNING naming the quota (`...PerDayPerProjectPerModel-FreeTier`) on the day's first 429. Raise it only after enabling billing |
| `DAILY_API_CALL_LIMIT` | `1400` | OPS-20: budget of the OpenAI-compatible endpoint (labeller, drift audit) per model name in `api_usage_log`. Not Gemini's quota — see `GEMINI_DAILY_CALL_LIMIT` |
| `SOFT_THRESHOLD` | *(unset)* | SYS-37: overrides the probe artifact's CV-chosen P(soft) threshold (0.39 for the 2026-09-22 artifact, `newscrawler/core/models/importance_probe.json`). Leave unset unless OPS-18 says the operating point must move. The probe's encoder (`intfloat/multilingual-e5-large`, ~2.2 GB) is loaded by the crawler in addition to MiniLM. |
| `CHUNK_MIN_TOKENS` / `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `40` / `80` / `20` | SYS-109 (ADR-008): L2 chunks are windows of at most 80 words, so MiniLM's 128-token input (~83 Indonesian words) sees all of each one; they were 80 / 450 / 50. DBT-13: whitespace-token bounds of the L2 chunks; `HierarchicalChunker()` reads them as its defaults and refuses `overlap >= max` or `min > max` at start-up. Changing them changes the L2 vector count (SYS-41). |
| `OPENAI_API_KEY` | — | OPS-20: OpenAI-compatible endpoint (SumoPod). Used by the offline gold-set labeller / drift audit and, since 2026-10-04, by the **newsletter's cluster summaries** (SYS-68, ADR-001); never in the per-article crawl path. Knowledge extraction still calls Gemini until SYS-39 decides |
| `OPENAI_BASE_URL` | — | e.g. `https://ai.sumopod.com/v1` |
| `OPENAI_MODEL` | `deepseek-v4-flash` | Labelling and summary model; a reasoning model is called with thinking disabled |
| `NEWSLETTER_LLM_PROVIDER` | *(empty)* | SYS-68: who writes the summaries. Empty prefers the OpenAI-compatible endpoint when `OPENAI_API_KEY` is set, then Gemini; `openai` / `gemini` force one (a forced provider without its key means no summaries, never the other provider) |
| `NEWSLETTER_MIN_SUMMARY_SHARE` | `0.8` | SYS-68: a digest with a smaller share of real summaries is logged at ERROR and noted on its `crawl_log` row (`digest degraded: Ringkasan AI: n/N ...`) |
| `NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS` | `5` | SYS-68: this many failed summary calls in a row stop the calls (an outage); a quota 429 stops them at once. The clusters left show their headlines and the notice at the top of the digest says how many |
| `NEWSLETTER_SUMMARY_TIMEOUT_S` / `NEWSLETTER_SUMMARY_MAX_TOKENS` | `60` / `600` | SYS-68: per-call timeout and output bound of the OpenAI-compatible summarizer |
| `NEWSLETTER_MAX_CLUSTERS_PER_STORY` | `2` | SYS-67: a section shows at most this many clusters of one story (a scandal covered from many angles used to fill 5 of 8 slots). The summarizer is asked once per section — before the summaries — which of the section's best 2× `NEWSLETTER_MAX_CLUSTERS_PER_TOPIC` clusters are the same story; the rest join "…dan N berita lainnya". `0` turns it off. A failed grouping shows that section as ranked and the footer says `pengelompokan cerita gagal di N bagian` |
| `KNOWLEDGE_LLM_PROVIDER` | empty (= `gemini`) | SYS-39 (#125, ADR-003): `openai` extracts on the OpenAI-compatible endpoint (SumoPod DeepSeek, `OPENAI_*`), `gemini` on Gemini. Empty keeps Gemini: the switch spends money, so it is made on purpose after the bake-off |
| `KNOWLEDGE_BATCH_SIZE` | `50` | Pending articles one extraction query fetches. A run keeps fetching until the queue is empty (it used to be the whole run) |
| `KNOWLEDGE_MAX_PER_RUN` | `6000` | Articles one `task=extract_knowledge` run may try (a normal day is ~4,000) |
| `KNOWLEDGE_WORKERS` | `4` | Provider calls in flight during extraction (ADR-004; 1 = serial). Bake-off: 4 workers, 0 errors, ~55 min per 4,000 articles. Lower it if `crawl_log` ever shows rate-limit failures |
| `KNOWLEDGE_DAILY_COST_LIMIT_USD` | `5.0` | Priced provider: the run stops before the next call once the day's `api_usage_log.cost_usd` for the model reaches this. A normal day is ~$1.3 off-peak, so this is a runaway guard; raise it for the one backlog run (~$27) |
| `KNOWLEDGE_MAX_CONSECUTIVE_ERRORS` | `5` | Failed calls in a row after which the run stops (the provider is down) |
| `KNOWLEDGE_ALLOW_PEAK` | unset | `true` lets a run start or continue inside SumoPod's peak window (UTC weekdays 01:00-04:00 and 06:00-10:00, double price) |
| `KNOWLEDGE_PRICE_INPUT_OFFPEAK` / `_PEAK`, `KNOWLEDGE_PRICE_OUTPUT_OFFPEAK` / `_PEAK` | `0.15` / `0.30`, `0.60` / `1.20` | USD per 1M tokens (owner, 2026-10-04); update when the price list changes |
| `KNOWLEDGE_MAX_OUTPUT_TOKENS` | `3000` | Reply cap of the OpenAI-compatible provider (SYS-78: at 1,200 about 1 article in 100 was cut mid-JSON, failed to parse on every retry and was dropped after 3 attempts). Only tokens used are billed; a cut reply logs `the reply was cut at max_tokens=` |
| `KNOWLEDGE_REQUEST_TIMEOUT_S` | `60` | Per-call timeout of the OpenAI-compatible provider |
| `EMBEDDING_MODEL_HF` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model |
| `VECTOR_DB_NAME_L1` | `NEWS_L1` | FAISS L1 index directory |
| `VECTOR_DB_NAME_L2` | `NEWS_L2` | FAISS L2 index directory |
| `DIGESTS_DIR` | `digests` | Newsletter output directory |
| `NEWSLETTER_CLUSTER_DISTANCE` | `0.30` | SYS-40: cosine distance at which the digest's average-linkage clustering stops merging (replaced DBSCAN_EPS: DBSCAN chained busy topics into one cluster) |
| `NEWSLETTER_MIN_CLUSTER_SIZE` | `2` | Min articles per digest cluster; smaller groups are counted in the section's "and N more" |
| `NEWSLETTER_MAX_CLUSTERS_PER_TOPIC` | `8` | SYS-40: clusters shown per topic section of the digest (ranked by size × distinct sources); the rest are one "…dan N berita lainnya" line |
| `FILTER_AUDIT_WEEKDAY` | `0` | OPS-18: the day (0 = Monday, -1 = off) the 05:30 health-check job also runs `scripts/audit_filter_drift.py` |
| `FILTER_AUDIT_PER_SIDE` / `FILTER_AUDIT_BATCH` / `FILTER_AUDIT_MAX_CALLS` | `100` / `20` / `15` | OPS-18: saved + rejected rows judged per week, rows per LLM call, call cap |
| `AUDIT_MIN_AGREEMENT_SAVED` / `_REJECTED` | `0.80` / `0.70` | OPS-18: judge agreement floors that alert; calibrated on the first run (healthy week: 0.87 / 0.78) |
| `AUDIT_CELL_MIN_N` / `AUDIT_CELL_MIN_AGREEMENT` | `20` / `0.80` | OPS-18: a source x category with this many decisions alerts under this agreement |
| `RAG_TOP_K` | `5` | Articles (source cards) behind one search answer |
| `RAG_MIN_SEMANTIC_SCORE` | `0.55` | The cosine similarity a paragraph needs to be a source. SYS-110 (#284): 0.55 is the old 0.60 on the scale `search_l2` used to report (`1 - d²/2` of FAISS's squared distance); the same hits pass |
| `RAG_LLM_PROVIDER` | `openai` | SYS-98 (#267, ADR-005): who writes the search page's answers. `openai` = SumoPod DeepSeek (`OPENAI_*`; owner decision 2026-10-07), `gemini` = Gemini (20/day free tier), empty = the newsletter's rule. A forced provider without its key: the page shows articles with "Ringkasan AI sedang tidak tersedia", never the other provider |
| `RAG_DAILY_COST_LIMIT_USD` | `1.0` | SYS-98: the page's own spend per day, read from `api_usage_log` under `web:<model>` (never the extraction's key, so search never eats `KNOWLEDGE_DAILY_COST_LIMIT_USD`). ~$0.001 per answer; at the cap the page shows articles only until midnight |
| `RAG_ANSWER_TIMEOUT_S` / `RAG_ANSWER_MAX_TOKENS` | `30` / `600` | SYS-98: per-answer timeout and output bound (OpenAI-compatible provider) |
| `RAG_FILTERED_K` | `200` | SYS-92/SYS-100: paragraphs the semantic search fetches when a topic / portal / date filter is set, before filtering on the database's metadata (the keyword search filters in SQL) |
| `RAG_MIN_KEYWORD_COVERAGE` | `0.6` | SYS-103 (#273, ADR-006): a keyword hit below `RAG_MIN_SEMANTIC_SCORE` is still a source when it covers this share of the question's IDF-weighted words (0..1). Every candidate is scored on both signals (ADR-007); the log's `keyword_only=` counts the sources only the keyword half found. The words' document frequencies come from `pg_stats` (common words) and exact counts (rare words), cached per process for 24 h |
| `RAG_QUESTION_MAX_CHARS` | `500` | Longest question the page accepts |
| `RAG_WARM_AT_STARTUP` | `1` | SYS-102: load MiniLM and both FAISS indexes when the web app starts (a background thread; the log says `RAG warm-up done in Ns`). `0` = load on the first question |
| `SITEMAP_RECRAWL_COOLDOWN_DAYS` | `7` | Days before a sitemap with no `articles` row is offered to the article crawl again |
| `SITEMAP_MAX_FETCH_FAILURES` | `3` | SYS-09: runs that produced no article for a sitemap before `load_all_sitemaps` stops offering it; undo with `scripts/reset_fetch_failures.py` |
| `SITEMAP_SOURCE_FAILURE_RATIO` | `1.0` | OPS-15: the fraction of a run's attempted sitemaps that must fail before the run is considered source-wide (`1.0` = only when every one failed). Both this **and** `SITEMAP_SOURCE_FAILURE_MIN` must be met |
| `SITEMAP_SOURCE_FAILURE_MIN` | `20` | OPS-16: the minimum number of failures before a run can be called source-wide. A ratio alone is undefined at small N — with 3 rows left in a source's queue and all 3 dead, "100% failed" is evidence about those 3 URLs, not about the source, and sparing them meant they were re-fetched every run forever with no cooldown |
| `SOURCE_THROTTLE_STREAK` | `10` | SRC-55: this many HTTP 403/429 answers in a row from one source stop its full-text run. Since SYS-66, `ConnectionError`/`ReadTimeout after N retries` count too (a host refusing us); `NameResolutionError after N retries` (a host that no longer resolves) never does, so dead hosts retire under SYS-62 instead of stopping the source every run. The streak's rows and the rows not yet fetched are left untouched (no strike, no `last_fetch_error`, no cooldown), so a rate limit costs the rest of that run, not the URLs. The run's `crawl_log.error_msg` starts `throttled (SRC-55): ...`; ERROR in the log when the source served nothing before the streak (a block, not a limit) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | Scheduled-crawl and health-check alerts (OPS-01). Unset = nothing can be sent: each alert is logged at ERROR and queued in `logs/telegram_outbox.jsonl` (newest 20 kept, OPS-34), and the first send after both are set delivers them as `[delayed]` |
| `HEALTH_ALERT_ON_NO_CHANGE` | `true` | OPS-13: `false` mutes the daily alert on a red day whose per-outlet statuses all match the previous run (exit code unaffected; NEW/CHANGED/RECOVERED always notify) |
| `SCHEDULE_SOURCE_TIMEOUT` | `1200` | OPS-19/OPS-22: per-source seconds before the scheduled crawl **kills** that source's worker process and moves on. The kill completes before the next source starts, the source's `crawl_log` row is closed as `failed` (`killed by run_scheduled_crawl: …`), and the next source gets a fresh worker (one more ~2 min model load). It is a guard against a hung source, sized above a healthy one: the five sources that hit the 1,000-row cap take 580–950 s, and one connection burst adds ~300 s (DETIK: 885 of the old 900 s on 2026-09-28, OPS-28) |
| `SCHEDULE_RUN_BUDGET` | `12600` (3 h 30 min) | OPS-22: no source is started once elapsed time + one `SCHEDULE_SOURCE_TIMEOUT` would pass this. The rest are reported as skipped, so the summary is sent before Task Scheduler's 4 h `ExecutionTimeLimit` kills the process silently. Keep it below that limit minus one timeout |
| `SCHEDULE_SOURCE_TIMEOUTS` | `MEDIAINDONESIA=1500,KUMPARAN=1800` | OPS-28: per-source timeouts, `NAME=seconds,...`, never below `SCHEDULE_SOURCE_TIMEOUT`. The run budget uses the source's own timeout. MEDIAINDONESIA runs serially and takes 880–947 s on a normal run (queue 11,460), so it keeps the same ~300 s burst allowance above that; a row cap instead would make its backlog permanent. SYS-70: KUMPARAN is paced at ~1 req/s, so it fetches its whole queue (~1,000–1,300 s) instead of stopping at its rate-limit wall |
| `REQUEST_MAX_RETRIES` | `3` (`.env`: 3, was 5) | SYS-66: retries of a connection error / read timeout per fetch. Each retry is preceded by a backoff sleep, so 5 would cost ~23 s per URL on a dead host |
| `REQUEST_RETRY_BACKOFF_S` / `REQUEST_RETRY_BACKOFF_MAX_S` | `1.0` / `8.0` | SYS-66: retry n sleeps `base * 2**n` (±50% jitter), capped: 1, 2, 4 s for 3 retries |
| `REQUEST_RETRY_AFTER_MAX_S` | `60` | SYS-70: a 429/503 with a `Retry-After` at most this long pauses the whole host and is retried once |
| `CRAWLER_USER_AGENT` / `CRAWLER_CONTACT` | `NewsAggregatorBot/1.0` / unset | SYS-70: the crawler identifies itself; a contact (URL or `mailto:`) is appended as `(+contact)` when set. Owner decision 2026-10-03: no contact yet |
| `BROWSER_UA_HOSTS` | `beritasatu.com,investor.id,tribunnews.com` | SYS-70: hosts (suffix match) that answer 403 to the bot UA and keep the old browser UA. Measured with `scripts/experiments/probe_bot_ua.py` |
| `HOST_MIN_INTERVAL_S` / `HOST_MAX_CONCURRENCY` | `kumparan.com=1.0` / unset | SYS-70: per-host politeness, `host=value,...` (suffix match). Minimum seconds between request starts, and most requests in flight. Owner decision 2026-10-03: throughput kept (20 threads), pace only where measured |
| `FAISS_RENAME_RETRIES` / `FAISS_RENAME_BACKOFF_S` | `5` / `0.2` | SYS-64: the FAISS commit rename and roll-forward moves retry on a transient Windows `PermissionError` (WinError 5): 0.2, 0.4, 0.8, 1.6, 3.2 s |
| `AUDIT_MIN_JUDGED_SHARE` | `0.5` | OPS-37: a drift-audit side judged on less than this share of its sample is a failed audit (`crawl_log` failed, exit 1, alert), not a quiet week |
| `FILTER_AUDIT_TIMEOUT_S` | `1800` | OPS-37: the health check stops a drift audit that has not exited by then and alerts |
| `DB_LIVENESS_DEADLINE_S` / `DB_LIVENESS_FAILS_BEFORE_ALERT` / `DB_LIVENESS_STATE` | `20` / `2` / `logs/db_liveness_state.json` | OPS-36: `SELECT 1` deadline, failed probes in a row before the DOWN alert, state file |
| `SCHEDULE_LOG_DIR` / `SCHEDULE_LOG_KEEP` | `logs/` / `28` | OPS-27: where the scheduled crawl writes `scheduled_crawl_<YYYY-MM-DD_HHMM>.log` (gitignored), and how many run logs are kept (two runs a day = 14 days) |
| `SCHEDULE_INIT_TIMEOUT` | `1200` | OPS-22: seconds the worker process may take to build the crawler (`init_crawler()`) before the start counts as failed |
| `SCHEDULE_FAILED_STARTS_BEFORE_STOP` | `2` | OPS-32: after this many sources in a row whose worker could not be built, the run stops. The remaining sources are not started, and the summary says `STOPPED: the crawler could not start N times in a row (<reason>)` |
| `TELEGRAM_OUTBOX` | `logs/telegram_outbox.jsonl` | OPS-32: alerts that could not be sent (network, 429, 5xx) after two retries. The next send delivers them first, marked `[delayed; queued <time>]`. The newest 20 are kept |
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
Extracts pending articles, finance topics first (then newest), until the queue is empty or a stop condition fires (SYS-39): the peak window opens (unless `KNOWLEDGE_ALLOW_PEAK`), the day's dollar budget (`KNOWLEDGE_DAILY_COST_LIMIT_USD`, priced provider) or call budget (`GEMINI_DAILY_CALL_LIMIT`, Gemini) is spent, a per-day quota 429 comes back, `KNOWLEDGE_MAX_CONSECUTIVE_ERRORS` calls fail in a row, or `KNOWLEDGE_MAX_PER_RUN` articles were tried. The `crawl_log` row's note says what ran: `1,212/1,230 extracted; 959000 in / 411000 out tokens, $0.4000; stopped: peak hours (...)`. Safe to run repeatedly.

`scripts/migrate_api_usage_tokens.sql` was applied to `newsaggregator` on 2026-10-04 (owner-approved, after a verified `backup_db.py` dump `newsaggregator_20261004T133211Z.dump`); the usage insert names its three new columns. Run it on a weekend, or after 10:00 UTC on a weekday (17:00 WIB), when the price is off-peak; the 19:00 WIB crawl ends well before the next peak block. Not scheduled yet (owner's go).

### Newsletter generation (Phase 3)
```python
lambda_handler.process_event({"task": "newsletter"}, None)
```
Generates the digest of **yesterday** (OPS-38) to `digests/YYYY-MM-DD.md` (the full digest: every section, the archive) and the **5-minute edition** to `digests/YYYY-MM-DD-ringkas.md` (SYS-83, tracker #244: a 60-second block, 6-8 top stories, a one-line Sekilas list, at most 1,200 words; `newsletter_digests.categories->'_edition'` holds its words, story counts and whether the editor call fell back). The digest is of a finished day, and today's would be a partial one. Pass `{"task": "newsletter", "date": "2026-10-03"}` for another day (`date` is refused for any other task, and a malformed one fails before the crawler is built). The scheduled form is `scripts/run_scheduled_newsletter.py` (below).

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
**Run it as one worker** (no `--workers N`): conversations and the turns between a question's two requests live in this process's memory (ADR-005).

**How a question flows (ADR-005, tracker #272):**
1. `POST /api/query/form` finds the articles and renders the question with its source cards.
2. The answer placeholder then calls `POST /api/answer/{turn_id}`, which writes the answer through `RAG_LLM_PROVIDER`.
3. The answer's state is one of:
   - `ok`;
   - `unavailable`: no key, a daily quota, or `RAG_DAILY_COST_LIMIT_USD` reached;
   - `failed`: the reader gets "Coba lagi";
   - no articles: no model call at all.
4. The error itself goes to the log only. Each question logs `rag retrieve ms=… semantic=… fts=… articles=… kept=… keyword_only=… recent=… followup=… filters=…` and `rag answer status=… ms=… tokens=…/… cost=$…`.

**Retrieval (ADR-007):**
- FAISS (100 paragraphs, `RAG_FILTERED_K` with a filter) and the keyword half (20); paragraphs under 15 words are skipped.
- An article only one retriever found is scored on the other signal too: its stored vector's cosine, or its coverage.
- A question that asks for recent news re-ranks by recency for articles relevant by meaning. The cue sets the horizon and weight, logged as `recent=`: "hari ini / sekarang" 1 day 0.3, "pekan ini" 3 days 0.2, "terbaru" 7 days 0.1.
- A follow-up (`followup=True`) is retrieved with the session's last two questions, answered or not.
- `scripts/experiments/probe_rag_rank_breakdown.py --replay --followups --detail 5` prints the ranking read-only, with no model call.

`POST /api/query` is the one-call JSON API: `{"query", "topic", "source", "rentang", "date_from", "date_to", "session_id"}` → `{"answer_status", "answer", "numbers_unverified", "sources", "session_id"}`.

**The page's spend:** `SELECT * FROM api_usage_log WHERE api_name LIKE 'web:%' ORDER BY log_date DESC LIMIT 7;`

**Replay check:** `scripts/experiments/replay_rag_answers.py --base http://127.0.0.1:8000 --out <dir>` asks 15 fixed questions and a follow-up and checks each answer: citations in range, at most 120 words, no Markdown, English months or internal names.

The UI loads NEWS_L1/NEWS_L2 at start-up (`RAG_WARM_AT_STARTUP`). The crawler (another process) saves them after every source. Before a query, at most every `FAISS_RELOAD_CHECK_S` seconds (default 30), the UI compares the files' generation with the one it loaded and reloads a level that changed, so no restart is needed after a crawl (DBT-16, #51). `/api/health` shows both sides: `faiss_docs` is on disk, and `faiss_in_memory` (`loaded_at`, `docs`) is what this process searches. They differ only until the next query after a save.

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

**Shared memory (OPS-49).** The service sets `shm_size: 1gb`. Postgres puts parallel-query memory in `/dev/shm`, and Docker's default is 64 MB. When that runs out, a query fails with `could not resize shared memory segment ... No space left on device`. psycopg2 reports it as `DiskFull`, but the disk is not full. On 2026-10-12 the weekly filter-drift audit failed this way. Fixed the same morning, owner-approved:
- `backup_db.py` dump first;
- `docker compose -f docker/docker-compose.yaml up -d` recreated the container (~40 s), on the same named volume;
- row counts identical before and after.
Check it with `docker inspect newsaggregator-postgres --format '{{.HostConfig.ShmSize}}'` (1073741824).

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
| every 15 min | DB liveness (OPS-36) | `scripts/db_liveness.py` — registered 2026-10-04 as **"NewsAggregator DB Liveness"**; see "DB liveness (OPS-36)" |
| after each crawl | Store consistency check (OPS-04, OPS-29) | runs inside `scripts/run_scheduled_crawl.py` after its worker has closed; writes `crawler_health/store-consistency-<date>.json` and puts anything to act on in the crawl's Telegram line. `scripts/check_store_consistency.py` by hand for the full table |
| 07:00 | Morning crawl (OPS-19) | `scripts/run_scheduled_crawl.py` — registered 2026-09-25 as **"NewsAggregator Scheduled Crawl (morning)"** (owner decision); first unattended run 2026-09-26 07:00. `python __main__.py` remains the manual equivalent |
| 21:00 | Knowledge extraction (SYS-39, OPS-20) | `scripts/run_scheduled_extraction.py --wait-for-crawl 90` — registered 2026-10-04 as **"NewsAggregator Knowledge Extraction"**; off-peak, 8 h limit; see "Scheduled knowledge extraction" |
| 12:00 | Newsletter (OPS-38) | `scripts/run_scheduled_newsletter.py` — digests the previous day; registered 2026-10-04 as **"NewsAggregator Newsletter"** (owner decision), first run 2026-10-05 12:00; see "Scheduled newsletter (OPS-38)" |
| 19:00 | Evening crawl (OPS-19) | `scripts/run_scheduled_crawl.py` — registered as **"NewsAggregator Scheduled Crawl (evening)"** |

### Scheduled knowledge extraction (SYS-39, OPS-20) — registered 2026-10-04

`venv\Scripts\python.exe scripts\run_scheduled_extraction.py [--wait-for-crawl MINUTES] [--dry-run]` runs `task=extract_knowledge` through the crawler service (so it writes the `crawl_log` row, OPS-11), then sends one Telegram line: `4800/4830 extracted · 3800000 in / 1480000 out tokens, $1.50 · pending 84000 -> 79200 · stopped: <reason>`. A stop at the day's dollar budget or at the provider's peak window is normal and exits 0; `STOPPED:` (five failed calls in a row, a per-day quota), `FAILED` (every call failed, or an exception) exit 1; exit 2 means a crawl held the run lock and `--wait-for-crawl` (the job passes 90) ran out. Run log: `logs/scheduled_extraction_<YYYY-MM-DD_HHMM>.log`, newest 28 kept.

- **When:** 21:00 daily. The 19:00 crawl normally ends by 20:00 and the provider's peak window does not open until 08:00 WIB; Task Scheduler's 8 h limit ends a long run at 05:00, before the 07:00 crawl. Every article is its own transaction, so a killed run loses nothing.
- **Size:** `KNOWLEDGE_MAX_PER_RUN=20000`, 4 workers (~0.8 articles/s, ~2,900/h). A normal day is ~4,000 articles (~55 min, ~$1.3).
- **Backlog:** 84,606 articles; about 4 nights at the limits above. `KNOWLEDGE_DAILY_COST_LIMIT_USD=8` in `.env` is sized for those nights (~$27 in all, the owner's figure); **lower it to 3 once `pending` in the Telegram line stops falling by thousands** (a normal day costs ~$1.3, so $3 is a runaway guard).
- **First real run (2026-10-04 21:31 WIB, by hand):** 30-article smoke test $0.0097, then a 6,000-article run at $0.327 per 1,000, finance topics first; the KB went from 54 entities / 32 mentions to thousands (`kb_query --ticker ANTM --days 30`: 33 mentions across 17 portals).
- **Watch:** `crawl_log` rows `task='extract_knowledge'` (`article_count` and the note), `api_usage_log` (`cost_usd` per day), the parse-failure warnings in the run log (SYS-78 raised the reply cap to 3,000 tokens), and `pending` falling.
- **Pause it:** `Disable-ScheduledTask -TaskName "NewsAggregator Knowledge Extraction"`. To change provider: `KNOWLEDGE_LLM_PROVIDER` in `.env` (empty = Gemini, held to 20 calls a day).

### Repairing stored article bodies (SYS-73)

`scripts/repair_boilerplate_bodies.py` re-applies the body cleaner to what is already stored. Without arguments it is the read-only dry run (per-source report, `crawler_health/boilerplate-repair-dryrun-<date>.json`). `--apply --source NAME` repairs one source (owner decision 2026-10-04: per source, DETIK first):

```
venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py --apply --source DETIK --until 06:15 --block 1000
```

What it does, in order, holding the run lock throughout: back up `NEWS_L1`/`NEWS_L2` and the rows about to change to `backups/sys73_<SOURCE>_<stamp>/` (about 2.1 GB; delete it once the source is verified); delete the changed articles' vectors from both indexes (one atomic, generation-checked save each); one SQL transaction that deletes their entity mentions (those articles are reset for extraction and re-extracted by the nightly job), deletes their chunk rows and writes the cleaned text; re-chunk and re-embed them from the stored text, `--block` articles per FAISS flush; recompute the counters of the entities that lost mentions (SYS-20). A telegram line reports the result.

- **When:** only when no crawl, newsletter or extraction is due. The crawls hold the lock from 07:00 and 19:00 for up to 4 h, the newsletter job is at 12:00 and the extraction at 21:00 (it waits up to 90 min for the lock), so the free windows are about 02:00-06:30 and 08:30-11:30. Pass `--until HH:MM` so no new block starts after that time; the 12:00 newsletter exits 2 if the lock is held. `--until` is the **next** HH:MM: `--until 06:15` given at 20:00 means tomorrow 06:15. A deadline less than 15 minutes away (`MIN_RUN_MINUTES`) is refused with exit 2 before the backup and the deletes. SYS-111 (#287): before that fix it meant today's 06:15, and an evening run deleted 358,398 L2 rows, then stopped at once.
- **Cost:** about 0.25 s per article, a 5 min SQL step per 10,000 articles and 1-2 min for the backup: DETIK (10,413 articles, 56,858 chunk rows) took 44 minutes on 2026-10-05.
- **Interrupted or stopped at the deadline (exit 3):** the rewritten articles have no chunks yet and nothing else is inconsistent; `--apply --source NAME --rechunk-only` finishes it (`scripts/backfill_orphan_chunks.py --website NAME` does the same).
- **Refuses (exit 2)** while a crawl holds the run lock, while a crawl_log row is `started` in the last 4 h, or when `--until` is less than 15 minutes away. It is idempotent: a second run finds no article whose cleaned text differs.
- **Verify a source:** the dry run for it shows 0 changed; `scripts\check_store_consistency.py` is all zero; the source's L2 chunk rows equal its vectors in `NEWS_L2` with no NULL `embedding_id`; a query for the chrome text (`ADVERTISEMENT SCROLL TO CONTINUE WITH CONTENT`) returns fewer chrome chunks. DETIK, measured: chrome chunks in the top 20 for that query 10 -> 3, for `Lihat Juga : Video detikFinance` 4 -> 0; 19 remaining pattern hits are ordinary prose ("kami melihat juga").
- **Restore:** copy the backup's `L1`/`L2` directories back over `NEWS_L1`/`NEWS_L2` and restore the rows from `rows.json` (articles' old text, chunk rows, entity mentions); do this only with the run lock held.

### Re-chunking stored sign-off fragments (SYS-105)

The chunker used to keep an article's trailing sign-off as its own L2 chunk ("(jon)", "--", "Editor: X"). It now merges a short last paragraph backward, and the search skips any matched paragraph under 15 words. `scripts/rechunk_stale_chunks.py` brings the stored articles in line.

- **Which articles:** those that hold an L2 chunk under `--min-words` (default 15) and that the chunker now cuts differently. `--min-words 80` takes every article the change touches (54,247 on 2026-10-08, about 4 h).
- **Dry run (the default, read-only):** per source, the articles, their chunk rows, and their L2 chunks under 10 words before -> after. On 2026-10-08: 3,075 articles, 17,222 chunk rows, 1,616 -> 0.

```
venv\Scripts\python.exe scripts\rechunk_stale_chunks.py
venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --apply --until 11:30
```

`--apply` (every source, or `--source NAME`) holds the run lock throughout and runs these steps in order:
1. One backup to `backups/sys105_ALL_<stamp>/`: FAISS plus the rows.
2. Delete the targets' vectors (atomic, generation-checked saves).
3. One SQL transaction: detach their entity mentions from the chunk rows (the mentions stay; the text does not change, so nothing is re-extracted) and delete their chunk rows.
4. Re-chunk and re-embed per source, one FAISS flush per `--block`.
5. Re-attach every detached mention to its article's new L1 chunk.

Exits:
- 2 while a crawl holds the run lock or a crawl_log row is `started`, or when `--until` is less than 15 minutes away (nothing touched, SYS-111);
- 3 at the `--until` deadline: run it again, and steps 4-5 pick up articles without chunks and mentions without a chunk.

The same windows as the SYS-73 repair apply.

### Settling a source's out-of-scope links (SRC-60)

A crawler can call a listed URL out of scope (`Crawler.out_of_scope_reason`). KUMPARAN keeps only its newsroom desk accounts (`kumparan*`) and the partner newsroom `pandangan-jogja`; readers' blog posts are dropped. New listings skip them; the crawl_log note counts them (`N URL(s) out of scope: …`), and `check_crawlers.py` reports `out_of_scope` for its sample. `scripts/settle_out_of_scope_links.py --source NAME` applies the same rule, imported from the crawler, to what is already stored.

- **Dry run (the default):** what would go, and a check on the rule: how many of the articles to delete, and of those kept, carry KUMPARAN's reader-post disclaimer. On 2026-10-08: 364 sitemaps, 357 articles, 321 with the disclaimer to delete, 0 of the 1,521 kept.

```
venv\Scripts\python.exe scripts\settle_out_of_scope_links.py --source KUMPARAN
venv\Scripts\python.exe scripts\settle_out_of_scope_links.py --source KUMPARAN --apply
```

`--apply` holds the run lock and runs these steps in order:
1. Back up to `backups/src60_<SOURCE>_<stamp>/`.
2. Delete their vectors.
3. One SQL transaction: delete their entity mentions, chunk rows and articles, and set the sitemaps `rejected_filter`.
4. Recompute the entity counters (SYS-20).

A second run finds nothing.

**Then repair KUMPARAN's bodies (SRC-61):** `repair_boilerplate_bodies.py --apply --source KUMPARAN`. The body cleaner now drops KUMPARAN's page header (the headline again, the desk or writer, `·waktu baca N menit`). Run the settle first, so the reader posts are not repaired only to be deleted.

### Re-chunking the corpus to the encoder window (SYS-109, ADR-008)

The L2 chunks became windows of at most 80 words (overlap 20), because MiniLM embeds only 128 tokens, about 83 Indonesian words. Articles crawled since then are chunked that way. The stored ones are re-chunked by `scripts/rechunk_stale_chunks.py --all`. It is **L2-only**: L1 rows, L1 vectors and entity mentions are never touched.

```
venv\Scripts\python.exe scripts\backup_db.py
venv\Scripts\python.exe scripts\migrate.py                       # DBT-64's indexes first: chunk deletes check the mention FK
venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --all    # dry run: articles, L2 rows before -> after
venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --all --apply --until 06:15   # the NEXT 06:15 (SYS-111)
venv\Scripts\python.exe scripts\rechunk_stale_chunks.py --apply --resume --until 11:30   # if it stopped (exit 3)
```

**What `--apply` does, in order:**
1. **One backup:** `backups/sys109_ALL_<stamp>/`, holding a copy of `NEWS_L2` and `l2_rows.jsonl` (the deleted L2 rows).
2. Delete the targets' L2 vectors (one atomic save) and L2 rows (one transaction).
3. Re-chunk per source: 50 articles per embedding batch, one FAISS flush per 5,000.
4. `ANALYZE chunks`.

**Scale (dry run 2026-10-08):**
- 100,466 articles; L2 358,162 → 713,589 rows.
- NEWS_L2 grows from ~1.8 GB to ~3.5 GB on disk and in each process that loads it.

**Verify:**
- the dry run shows `TOTAL 0`;
- `check_store_consistency.py` is all zero;
- `SELECT count(*) FROM chunks c JOIN articles a USING (sitemap_id) WHERE chunk_level = 2 AND token_count > 80` = 0;
- the replay probe.

**Rollback:**
1. Under the run lock, copy the backup's `NEWS_L2` back.
2. Delete the L2 rows of the re-chunked articles.
3. Re-insert `l2_rows.jsonl`.
4. Set `CHUNK_*` back to 80/450/50 in `.env`.

### Scheduled newsletter (OPS-38) — registered 2026-10-04

`venv\Scripts\python.exe scripts\run_scheduled_newsletter.py [--date YYYY-MM-DD] [--dry-run]` builds the digest of the previous day (or `--date`; today and later are refused), through `crawler_service.generate_newsletter`, so it writes the `newsletter_digests` row, the `digests/<date>.md` file and a `crawl_log` row (`website='ALL'`, `task='newsletter'`, OPS-11). It then sends one Telegram line:

- `2026-10-03: 2052 articles, 320 clusters · 94/94 summaries · digests/2026-10-03.md` — a clean digest.
- `DEGRADED 2026-10-03: ... · <why>` — summaries are mostly headlines (SYS-68: the provider's daily quota, or five failed calls in a row), or the 5-minute edition was not built (`5-minute edition not built: <reason>`). Exit 0; the reader's documents say "Sebagian ringkasan tidak tersedia hari ini. N berita hanya ditampilkan judulnya." at the top (SYS-84).
- `EMPTY <date>: no articles for the day` — exit 1; the crawls did not run or saved nothing.
- `FAILED <date>: <Exception>: <text> · log <path>` — exit 1.

Exit 2 = refused by the run lock (OPS-26): a scheduled crawl holds FAISS in memory, so the run says so in its log and does nothing (no database, no Telegram line; Task Scheduler's "Last Run Result" is the only trace). Run log: `logs/scheduled_newsletter_<YYYY-MM-DD_HHMM>.log`, newest 28 kept.

**What the reader gets (OPS-43 #243, since 2026-10-05; OPS-40 #235 before).** After the operator's summary line, the job sends (1) a **message** in Telegram HTML: `Rangkuman Berita · Minggu, 4 Okt 2026 (±5 menit)`, the edition's "Hari Ini dalam 60 Detik" sentences as bullets, and `Buka PDF untuk N berita utama dan sekilas lainnya.` (`notify_telegram.send_html`), then (2) the **edition as a phone PDF**, `digests/<date>-ringkas.pdf` (OPS-42: 105 × 228 mm, a phone's shape, 11.5 pt body; a story may continue on the next page after its title and first sentence -- owner decision 2026-10-05; ~7-8 pages), captioned `Rangkuman Berita · Minggu, 4 Okt 2026`. The full digest is the archive: it stays in `digests/` and is not sent. Without an edition (it failed, or no story had a summary) the message says `Edisi 5 menit tidak tersedia hari ini; terlampir edisi lengkapnya.` (plus the degraded notice when summaries are missing) and the full digest's A4 PDF follows, as before OPS-43. Each step's failure is a Telegram line to the operator (`reader message not delivered to Telegram`, `PDF <date> not made: ...`, `PDF <date> built but not delivered to Telegram: <path>`) and a WARNING in the run log; a PDF that cannot be made turns the message's last line into `PDF tidak tersedia hari ini.`, and a PDF the message promised that then does not arrive (its upload failed, or the full digest's could not be made after the message went out) is followed by a second message saying the same (OPS-44); the exit code stays 0 because the digest exists. Neither the message nor a file is queued in the outbox: send them again by hand, e.g. `venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'scripts'); from notify_telegram import send_document; send_document(r'digests\<date>-ringkas.pdf', 'Rangkuman Berita · <tanggal>')"`. Rendering: `newscrawler/core/newsletter_pdf.py` (reportlab, Arial from `C:\Windows\Fonts`, built-in Helvetica when it is missing); emoji in headings are dropped, any other character the font cannot draw (CJK) shows as `?`; a whole story stays on one page and a section heading stays with its first story (OPS-41). Preview a day's files and PDFs without touching the database: `venv\Scripts\python.exe scripts\experiments\replay_newsletter_edition.py --date YYYY-MM-DD` (calls the LLM, ~100 calls). The PDFs are git-ignored like the markdown.

**HTML entities in stored headlines (SYS-88 #249).** Some sitemaps escape titles once (`Jatim &amp; Kalsel`) or twice (`&amp;amp;`, DETIK). Since 2026-10-05 a headline is unescaped at ingest (`Crawler._get_sitemap`, `_get_page_title`) and wherever the newsletter reads one, so readers never see an entity. The rows stored before are fixed by `venv\Scripts\python.exe scripts\unescape_stored_headlines.py` (a dry run by default: count per source and samples; 2,410 rows on 2026-10-05); `--apply` first writes every changed row's old and new headline to `backups/sys88_headlines_<timestamp>.json`, then updates them in one transaction and re-counts (exit 1 if any are left); `--restore <that file>` undoes it. It writes no FAISS and needs no run lock.

**Why 12:00 and not the ticket's 06:30.** A day's digest is built from that day's `sitemaps.posted_at`. The 19:00 crawl runs for up to 4 h, but what is published after it starts is fetched by the 07:00 crawl, which can run until 11:00. A 06:30 digest of yesterday would miss those hours for good. 12:00 clears the longest allowed morning crawl. Registered (owner decision 2026-10-04, 12:00) as **"NewsAggregator Newsletter"** with the crawl jobs' settings (battery, wake, `StartWhenAvailable`, `MultipleInstances IgnoreNew`) and a 1 h limit, working directory the repo; check it with `Get-ScheduledTask -TaskName "NewsAggregator Newsletter" | Get-ScheduledTaskInfo`. Pause it with `Disable-ScheduledTask -TaskName "NewsAggregator Newsletter"`. The first run (2026-10-05) digests 2026-10-04 and replaces the stray partial-day row (`newsletter_digests` upserts on `digest_date`). Done-when evidence still to come: three consecutive daily digests, each with a `crawl_log` row and its Telegram line.

`task=newsletter` through `process_event` is the manual equivalent and is **not** guarded by the run lock (it writes no FAISS): it reads Postgres and the embedding model. The summaries' daily call count is in `api_usage_log` under the summarizer's model name; with DeepSeek there is no daily cap to fit, and `GEMINI_DAILY_CALL_LIMIT` (20) applies only if `NEWSLETTER_LLM_PROVIDER=gemini`.

### Scheduled crawl (OPS-19) — registered 2026-09-25

**Paused sources** (`DEFAULT_EXCLUDED` in `scripts/run_scheduled_crawl.py`, each against an open ticket; `--website` cannot bring one back in): **TEMPO**, since 2026-10-03 (SRC-56 #205: Cloudflare blocks automated clients by fingerprint; real browsers get in). It comes back when Tempo grants access. The 05:30 health check keeps sampling it.

Two Task Scheduler jobs, **"NewsAggregator Scheduled Crawl (morning)"** (07:00) and **"(evening)"** (19:00), both running `venv\Scripts\python.exe scripts\run_scheduled_crawl.py` with the repo as the working directory. Settings: runs on battery and doesn't stop on battery, StartWhenAvailable, WakeToRun, a 4 h ExecutionTimeLimit, and `MultipleInstances=IgnoreNew`, so a slow morning run never overlaps the evening one. Inspect with `Get-ScheduledTask -TaskName "NewsAggregator*" | Get-ScheduledTaskInfo`. Verified the same night through a temporary task (`--website ERAID --phase sitemap`): LastTaskResult 0, crawl_log row 628 `completed` (+7), no leftover worker. Schedule on that date: 27 sources (HEALTHY minus VIVA; GRIDID retired). Pause it with `Disable-ScheduledTask -TaskName "NewsAggregator Scheduled Crawl (morning)"` (and evening).

`scripts/run_scheduled_crawl.py` is the scheduled entry point for the crawl itself. Two phases, in this order: `task=sitemap` for every scheduled source, then `task=full_text` for `SCHEDULE_FULL_TEXT_WEBSITES`. Listing first for everyone, so a slow source's fetch phase cannot delay another source's listing.

One model load in the normal case. `init_crawler()` costs ~2 min and ~4 GB RSS, so it runs once in a worker **process** (`newscrawler/tools/source_worker.py`) and the sources run one after another inside it. The wrapper process only dispatches, counts and reports. A source that exceeds `SCHEDULE_SOURCE_TIMEOUT` has its worker killed, and the kill finishes before the next source starts (OPS-22). This used to be a worker thread. Python cannot kill a thread, so the timeout never freed the caller, and an abandoned source would have kept writing the same service state and FAISS stores as the next one. A kill is safe for the stores: FAISS swaps are atomic (DBT-10), and chunk dedup is keyed on SQL (SYS-17/25), so a kill between the FAISS save and the SQL insert is repaired on the sitemap's next attempt. A killed source's `crawl_log` row reads `status='failed', error_msg='killed by run_scheduled_crawl: exceeded …'`. A worker that dies on its own reads `worker process crashed (exit code 3221225477 = 0xC0000005 access violation); stack (faulthandler) in logs\scheduled_crawl_….log` (a native crash) or `worker process died (exit code N)` (SYS-52). Nothing killed those; open the log. `SCHEDULE_RUN_BUDGET` stops starting sources in time to send the summary.

**Order (OPS-28).** `full_text` runs the source whose last *completed* `full_text` is oldest first (never-completed sources before all others). The first scheduled run proved the budget does not fit the whole fleet at 1,000 rows per source (11,372 s for 27 sources). A fixed alphabetical order therefore starved the same tail source every run (WARTAEKONOMI, skipped on 2026-09-26). Now a skipped source is first next time. Before the phase the run logs the order and the projected phase time from each source's last completed run. When the projection exceeds the budget, the summary says `full_text projected Ns > budget Ms`. The `sitemap` phase keeps HEALTHY order (7 minutes for all 28).

**A network outage does not stop the worker from being built (OPS-32, #193).** Every model the crawler loads (the FAISS embedding model, the probe's e5-large, the newsletter's model) is loaded from its snapshot directory in the local Hugging Face cache (`~/.cache/huggingface/hub`, or `HF_HUB_CACHE`/`HF_HOME`), so building the crawler never calls huggingface.co. `HF_HUB_OFFLINE` is not enough with transformers 4.57.3, which calls `model_info()` for large-vocabulary tokenizers even in offline mode. A model that is not cached is downloaded as before, with a WARNING naming it. If the worker still cannot be built (a corrupt index, a missing probe artifact, OOM), `SCHEDULE_FAILED_STARTS_BEFORE_STOP` failed starts in a row stop the run with one reason, instead of failing every remaining source for the same cause. A summary that cannot be sent is queued in `TELEGRAM_OUTBOX` and arrives with the next message.

**The encoders are pinned to a revision, and a moved `refs/main` stops the build (SYS-61, #198).** "The cached snapshot" is whatever `refs/main` names, and any online load by Hub id moves `refs/main` when upstream has moved. So each artifact records the revision it was built with:
- the probe: `embedding_revision` in `newscrawler/core/models/importance_probe.json` (e5-large `3d7cfbda…`, checked 2026-09-28: 40 gold test rows re-embedded with it match the committed embedding matrix at cosine 1.000000);
- each FAISS pair: `NEWS_L*/encoder.json` (`{"model", "revision"}`), committed with the pair by every crawl save (MiniLM `e8f8c211…`; 40 stored vectors of each index re-embedded at cosine 1.000000 the same day). An index saved before SYS-61 has none; it loads with a WARNING, and its next crawl save writes one. A script that only deletes vectors (repair, dedupe) keeps the record the pair had.

Building the crawler, the web app or a FAISS script against another revision raises `ProbeArtifactError` or `EncoderRevisionError`. Both messages name both revisions. In the scheduled run the OPS-32 breaker turns that into one `STOPPED:` reason. Check with `scripts/experiments/probe_encoder_revision.py` (the probe) and `... --faiss NEWS_L1` (an index); both are read-only.

**Pick up a newer revision** only on purpose, as one change:
1. Download it: one online `SentenceTransformer("<hub id>")` in the venv moves `refs/main`. From then on nothing that uses that encoder builds.
2. e5-large (the probe): retrain with `scripts/train_importance_probe.py`. It embeds the gold set with the new revision (its cache is keyed by revision), must pass the gates again, and records the revision. Then re-run `--backfill` so `articles.topic` comes from the new probe.
3. MiniLM (FAISS): the stored vectors are in the old space, so the indexes must be rebuilt from `chunks` with the new revision. That is a full re-embed, not an append; plan it as its own ticket.
4. To back out instead, write the old hash back into `~/.cache/huggingface/hub/models--<org>--<name>/refs/main`. The old snapshot directory is still there.

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

**The token is a password** (OPS-33 #194). The Bot API puts it in the URL path (`/bot<TOKEN>/sendMessage`), and an HTTP client's exception message includes that path. `notify_telegram.py` logs everything through `redact()`, which writes `bot<redacted>`. Anything else that calls the Bot API must do the same. If a token has reached a log, an issue or a handoff: in @BotFather send `/revoke`, pick the bot, put the new token in `.env`, test with step 5, then scrub the old copies. `grep -rE "bot[0-9]+:[A-Za-z0-9_-]{30,}" logs/` must find nothing.

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
Per model and day: `call_count`, `input_tokens`, `output_tokens` and `cost_usd` (SYS-39; zeros before 2026-10-04, when tokens were not recorded). Extraction is bounded by the dollar budget for a priced provider and by `GEMINI_DAILY_CALL_LIMIT` for Gemini, see the env table. Spend this week:
```sql
SELECT log_date, api_name, call_count, input_tokens, output_tokens, cost_usd
FROM api_usage_log WHERE log_date >= CURRENT_DATE - 7 ORDER BY log_date DESC, api_name;
```
The summarizer counts calls on the same model name but records no dollars, so `cost_usd` is extraction's spend.

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

### Is a run going, or is a `started` row an orphan? (OPS-39, #232)
`SELECT log_id, website, task, started_at FROM crawl_log WHERE status = 'started'` answers "is a run going?" only for rows younger than their job's Task Scheduler limit: 8 h for `extract_knowledge`, 4 h for everything else (`newscrawler/tools/crawl_log_orphans.py`). An older row belongs to a run that Task Scheduler ended or that crashed. The 05:30 health check sends `📋 NewsAggregator crawl_log: N row(s) still 'started' past their job's time limit ...` when there is one. Close them with `venv\Scripts\python.exe scripts\close_abandoned_crawl_log.py` (dry run by default; `--apply` backs the rows up to `backups/ops39_crawl_log_<timestamp>.json`, sets `status = 'failed'`, `finished_at = started_at`, `error_msg = 'abandoned: no run owned this row (closed <date>, OPS-39)'`; `--restore <file>` undoes it). A row younger than its limit is never touched.

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
If yesterday's digest is missing after 12:30 WIB (once the OPS-38 job is registered), run `scripts/run_scheduled_newsletter.py` by hand and read the newest `logs/scheduled_newsletter_*.log`.

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

**A transient failure is a strike only when it repeats** (SYS-62, 2026-09-28). The ratio above is decided per run, but an outage can be four minutes of one batch. On 2026-09-28 07:34, a ConnectionError burst inside a healthy DETIK run (93 of 1,000 failed) put a strike on 92 of its newest, working URLs. KUMPARAN's `HTTP 403` (572 rows) and VIVA's `HTTP 502` (253 rows) had the same shape, and 36 of 36 of those URLs sampled that day fetched fine. So `_record_fetch_failures` sorts every reason into one of three classes (`CrawlerServiceImpl._failure_class`), in every run:

| class | reasons | not source-wide | source-wide |
|---|---|---|---|
| per-URL | `HTTP 404`, `HTTP 410`, `soft-404: …` | strike | strike |
| transient | `<Error> after N retries` (connection, timeout, TLS), `HTTP 403`, `408`, `429`, `5xx` | **strike only if the row's previous `last_fetch_error` was transient too**; otherwise store the reason and stamp the cooldown, no strike | spared, cooldown-stamped |
| page | everything else: an extractor exception, `empty document`, a redirect loop, another 4xx | strike | spared, cooldown-stamped |

A URL that is unreachable for good still retires, one attempt (one cooldown) later than a 404: its first transient failure is recorded, and every one after that is a strike. BISNIS's 3-row, 403-blocked queue is that case (OPS-16 point 1). A run with transient failures persists a note on its `crawl_log` row (`status='completed'`), e.g. `transient fetch failures: 92/1000; 92 not counted (first transient failure, cooldown-stamped), 0 counted (transient again). Reasons: 'ConnectionError after 5 retries': 92`. So a burst can be found with SQL: `WHERE error_msg LIKE 'transient fetch failures%'`. Because a first transient failure is recorded without a strike, `last_fetch_error` can be set on a row whose `fetch_failures` is 0. The reason query above filters on `fetch_failures > 0` and so leaves those rows out. Drop that filter to see them.

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

**`rejected_filter` can be wrong when a sitemap already has FAISS evidence (DBT-20, #70):** `backfill_sitemap_crawl_status.py` approximates the classification from a fresh headline-only re-check, not a re-run of the original filter -- for 582 MEDIAINDONESIA sitemaps (2026-09-18) that approximation disagreed with direct evidence (a real L1 vector already existed, meaning the original filter passed). `scripts/fix_rejected_filter_with_faiss_evidence.py [--website NAME] [--dry-run]` finds and corrects any `rejected_filter` row whose `sitemap_id` has an L1 FAISS vector, flipping it back to `pending`. Safe to re-run any time; reports "Nothing to fix" once clean. That alone does **not** get the article crawled: a `pending` row re-enters `load_all_sitemaps`' `ORDER BY posted_at DESC LIMIT 1000` queue behind everything newer for that source (12,000+ rows for MEDIAINDONESIA), and nothing is scheduled to drain it. `scripts/recrawl_faiss_orphans.py --website NAME [--dry-run] [--limit N]` does the re-crawl directly: it selects every sitemap that has an L1 vector but no `chunks`/`articles` row and hands exactly those to `crawl_newsdetails(specific_sitemaps=...)`, so they go through the normal fetch → filter → chunk → save path (the existing L1 vector is reused, SYS-17) regardless of queue position. It reports what the targets became afterwards; a target the filter now rejects, or whose page is gone, keeps its orphan L1 vector -- write those off with `scripts/recrawl_faiss_orphans.py --website NAME --write-off-remaining --dry-run`, then without `--dry-run`. It deletes (after backing up each docstore entry to `backups/dbt20_written_off_l1_<UTC>.json`) only the L1 vectors of orphans that can never get an article: `rejected_filter`, or `fetch_failures >= SITEMAP_MAX_FETCH_FAILURES` -- the same terminal rule SYS-54 applies in the crawl (DBT-27, #88). A row below the cap, `empty_extraction` or `pending` is retried by the pipeline and keeps its vector. It refuses while the scheduled crawl holds the run lock. DBT-26 (#85) tracks stopping `backfill_sitemap_crawl_status.py` from misclassifying evidenced rows in the first place.

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

**The crawl cleans up what it settles itself (SYS-54 #185, SYS-57 #191).** Each source's `full_text` asks the store for that source's sitemaps that can never get an article (no article, and `rejected_filter` or at `SITEMAP_MAX_FETCH_FAILURES`) but still have chunk rows, and removes their vectors and chunk rows. The vectors leave the in-memory indexes and are flushed with the source's own adds. The chunk rows are deleted only after that flush succeeded (the repair's order). This happens twice per source: when its block opens, which cleans up after an earlier run that was killed (OPS-22 timeout, worker crash, budget end) before its end, and after its last batch, which cleans up what this run settled. The log says `<SOURCE>: removed N vector(s) of sitemaps an earlier run settled terminal (SYS-57)` and `<SOURCE>: removed N vector(s) of sitemaps settled terminal this run (SYS-54)`. So the 5,292 queued VIVA sitemaps with June-era vectors no longer turn into `terminal … GROWING` when the crawl rejects them, even if VIVA times out that run. A failure of this step is logged at ERROR, and the next run of the source retries it. Not covered: vectors of a terminal sitemap that has **no** chunk rows. The check reports those as `l1/l2_no_chunks`, and the repair below removes them.

**After any script that moves rows to `rejected_filter`, run the check, then the repair** (OPS-25). That covers `reject_denied_categories.py`, `cleanup_soft_by_probe.py`, and the SRC-33/SRC-29 retirement scripts. A sitemap that was queued *with vectors* becomes terminal, so its vectors and chunk rows are orphans from that moment. That is how SRC-33's 06:30 retirement left 1,237 VIVA orphans after OPS-04's 01:23 repair. The checker now shows it as `terminal … GROWING` the same day. Since SYS-57, the next crawl of that source also removes them, but the repair does it now.

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

### Check entity counters against their mentions (SYS-20)
`entities.mention_count`, `first_seen_at` and `last_seen_at` are maintained by `insert_entity_mention`, only when it inserts a mention row (since SYS-20, #41; `kb_query --entity` ranks ambiguous names on `mention_count`). Drift should be 0:
```sql
SELECT COUNT(*) FROM entities e
LEFT JOIN (SELECT entity_id, COUNT(*) n, MIN(posted_at) lo, MAX(posted_at) hi FROM entity_mentions GROUP BY 1) m USING (entity_id)
WHERE e.mention_count <> COALESCE(m.n, 0) OR e.first_seen_at IS DISTINCT FROM m.lo OR e.last_seen_at IS DISTINCT FROM m.hi;
```
If it is not, `scripts/recount_entity_mentions.py --dry-run` lists the drift, and without `--dry-run` it backs the rows up to `backups/sys20_entity_counts_<UTC>.json` and recomputes them from `entity_mentions`. A seeded entity nobody has mentioned has `mention_count = 0` and no seen-dates.

### Weekly filter drift audit (OPS-18)
`scripts/audit_filter_drift.py` runs once a week inside the health-check job (`FILTER_AUDIT_WEEKDAY`). It samples up to 100 saved and 100 probe-rejected decisions from the last 7 days, spread across sources; category-denied rejects are left out because they're a publisher's signal. It asks the SYS-36 labeller (DeepSeek via `OPENAI_*`; `--provider gemini` also works) to judge them with the gold-set rubric. It writes a `crawl_log` row (`website='ALL'`, `task='filter_drift_audit'`, agreement in `error_msg`) and `crawler_health/filter_drift_<date>.json` with every disagreement. It alerts on Telegram when a side falls under its floor or a source x category cell under 0.80, marking what is NEW since the previous report. `--dry-run` shows the sample without a key. The disagreements are candidates for a SYS-36 re-label, not automatic actions.

**It never fails silently (OPS-37).** A side judged on less than `AUDIT_MIN_JUDGED_SHARE` of its sample, a missing labeller key (the row is closed `failed`, not left `started`), a crash, or no exit within `FILTER_AUDIT_TIMEOUT_S` each produce one Telegram line from the health check: `Filter drift audit (OPS-18) FAILED, exit N: nothing was measured this week`.
```sql
SELECT started_at, article_count, error_msg FROM crawl_log WHERE task = 'filter_drift_audit' ORDER BY log_id DESC LIMIT 5;
```

### DB liveness (OPS-36)
`scripts/db_liveness.py` runs `SELECT 1` with a hard client-side deadline (`DB_LIVENESS_DEADLINE_S`). On 2026-09-30 a stalled Docker engine still accepted TCP on 5431 but hung every query, which connect and statement timeouts alone do not catch. It sends one Telegram alert after `DB_LIVENESS_FAILS_BEFORE_ALERT` failed probes in a row (DOWN), and one on the first good probe after that (recovered). It never repeats in between, writes nothing to the DB, and never raises. `--check` probes and prints only.

Registered 2026-10-04 (PM decision) as **"NewsAggregator DB Liveness"**: every 15 minutes, working directory the repo, battery and `StartWhenAvailable` as the crawl jobs, `MultipleInstances IgnoreNew`, a 5 min limit. To re-create it use `New-ScheduledTaskAction` (python.exe, argument the script, `-WorkingDirectory` the repo), a `-Once` trigger with `-RepetitionInterval (New-TimeSpan -Minutes 15)` and `Register-ScheduledTask`.

Drilled 2026-10-04 21:16-21:18 with `docker stop newsaggregator-postgres` (2 min, no crawl running): the first failed probe changes nothing, the second sets `down` and sends the alert, a further probe while down repeats nothing, and the first probe after `docker start` sets `up` and sends the recovery. Row counts were identical before and after. A drill outside a crawl window costs nothing; during one it would fail that source's run.
When it alerts DOWN: `docker ps` (a hang means the Docker Desktop engine itself is stalled; `docker desktop restart` brought it back on 2026-09-30), then `venv\Scripts\python.exe scripts\db_liveness.py --check`.

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

**FAISS index corrupt or won't load** (DBT-10 #45, SYS-56 #190)
- Every save commits the pair as a whole. The new pair and a copy of the old one (`*.bak`) are written to `NEWS_L*.tmp`. One directory rename to `NEWS_L*.commit` is the commit point, and then the files are moved into `NEWS_L*`. A kill before the rename leaves the old pair (the `.tmp` is dropped by the next load or save). A kill after it leaves `NEWS_L*.commit`, and the next load or save finishes the move, logging `finished a save that was interrupted after its commit point (SYS-56)`. The previous generation is kept as `index.faiss.bak`/`index.pkl.bak`, and it is always one pair too.
- **Do not delete a `NEWS_L*.commit` directory by hand.** It is the newest committed generation. Starting the web app or any crawl finishes it.
- A pair that does not line up is refused at load with `CorruptIndexError: refusing to use NEWS_L2: index.faiss holds N vectors but index.pkl maps M positions`. Serving it would return the wrong documents, which is why it is refused. This can happen after a hand copy of one file or a torn save from before SYS-56. The store check reports it as `faiss_pair_mismatch`. Restore the `.bak` pair (below).
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

**`scikit-learn` not installed (needed for the digest's clustering)**
```bash
pip install scikit-learn
```

**Newsletter: 0 clusters produced**
- Check `NEWSLETTER_CLUSTER_DISTANCE` -- raise it (0.35) if related articles stay apart, lower it (0.25) if clusters mix stories. Neither the vectors nor the headline words can tell one scandal's angles from two cases of one institution (EXPERIMENTS.md "SYS-67"), so `NEWSLETTER_MAX_CLUSTERS_PER_STORY` asks the summarizer instead; a cluster that mixes two unrelated cases is only handled in its summary (the prompt says to summarize the event most articles are about), its "Sumber" count can still include a stray article.

**Newsletter: the digest lists headlines instead of summaries**
- The run log and, below 80%, the `crawl_log` row's `error_msg` and the Telegram `DEGRADED` line say why: `Ringkasan AI: 0/94 ... kuota harian habis` (the provider's quota), `layanan gagal berulang` (an outage: 5 failed calls in a row), or `tidak ada penyedia LLM yang dikonfigurasi` (no `OPENAI_API_KEY`/`GEMINI_API_KEY`). The numbers are in `newsletter_digests.categories->'_summaries'`. Since SYS-84 the reader's document carries no telemetry, only the notice at the top.
- SYS-82: a summary the model wrote but the code refused (not JSON, a field over its word limit, or a number that is not in the articles) is asked again once, then shows the headline list; `_summaries.rejections` counts the refusals by reason (`json`/`length`/`number`) and `_summaries.first_try` the answers accepted at once. Many `number` refusals mean the model is rewriting numbers ("13,3 juta" for "13.300.000"); the guard is on purpose (EXPERIMENTS.md, SYS-82 replay).
- Preview a day without writing to the database: `venv\Scripts\python.exe scripts\preview_newsletter.py --date YYYY-MM-DD` (file in `digests/preview/`; no `newsletter_digests` row, no `api_usage_log` increment).
- Check that today's articles exist: `SELECT COUNT(*) FROM sitemaps WHERE posted_at = YYYYMMDD;`

**Search page: "Ringkasan AI sedang tidak tersedia" on every question**
- Check the log for `rag answer unavailable:`. It names the cause: a missing key (`RAG_LLM_PROVIDER=… has no API key` at start-up), the provider's daily quota, or `spent $… today, RAG_DAILY_COST_LIMIT_USD=…`.
- The articles stay visible meanwhile. The cap resets when the DB's `CURRENT_DATE` changes. The container runs on UTC, so that is **07:00 WIB**, the same as the extraction budget.

**Search page: a filter returns nothing**
- Topic is `articles.topic` (SYS-92), portal is `sitemaps.sources`, dates are `sitemaps.posted_at`.
- Check that the scope has articles at all: `SELECT COUNT(*) FROM articles a JOIN sitemaps s USING (sitemap_id) WHERE a.topic = 'markets' AND s.posted_at >= 20261001;`

**RAG: FTS returns no results**
- Ensure `migrate_phase4.sql` has been run (adds `fts_vector` generated column).
- Check: `SELECT COUNT(*) FROM chunks WHERE fts_vector IS NOT NULL;`
