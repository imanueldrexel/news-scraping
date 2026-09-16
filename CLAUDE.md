# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

NewsAggregator: crawls ~32 Indonesian news portals (sitemap-driven), keeps only finance/economy articles (semantic filter), chunks + embeds them into local FAISS indexes, stores everything in PostgreSQL, and builds three products on top: an entity knowledge base (Gemini extraction), a daily markdown newsletter (DBSCAN clustering), and a RAG search web UI (FastAPI). See `PRD.md` for the design/product spec and `OPERATIONS.md` for the runbook (env-var table, SQL health queries, schedule).

**Two codebases live here; only one is active.**
- `newscrawler/` — the real, actively developed pipeline (Postgres + FAISS + sentence-transformers + Gemini). All work goes here.
- `services/`, `shared/`, `docker-compose.yml`, `MICROSERVICES_README.md`, `.env.example`, `check_dupe.py`, `scripts/init_chromadb.py|init_neo4j.cypher|pull_models.sh` — an **abandoned** Jan-2026 microservices prototype (Redis Streams / Neo4j / ChromaDB / Ollama), kept in the repo for reference only. Do not extend it and do not treat `.env.example` as the config reference for `newscrawler` — `OPERATIONS.md` has the real variable table.
- `model_inference/` — standalone IndoBERT+LSTM category classifier (13 classes) from the modelling notebooks; loads weights from hard-coded local paths and is not wired into the pipeline.

Always work in this main repo root, never under `.claude/worktrees/` — the app is run from here.

## Workflow: issue first, then code

Every new bug and every new or changed requirement gets a GitHub issue **before** any code is written — no matter how small the fix, and regardless of whether a human or Claude found it. Then reference the issue in the commit (`Fixes #N` closes it on merge; `Refs #N` links without closing).

- Repo: `imanueldrexel/news-scraping`. Use `gh` (installed at `C:\Program Files\GitHub CLI\gh.exe`, authenticated). From Bash: `"/c/Program Files/GitHub CLI/gh.exe" issue create …`.
- **Tickets are referred to by their ID, not the GitHub number.** Every issue title starts with `[AREA-NN]` — `SYS` pipeline · `OPS` observability/tooling · `SRC` per-source scraper · `DBT` tech debt — using the next free number for that prefix (`gh issue list --state all --search "[SYS-" --json title`). In conversation, commit subjects, `EXPERIMENTS.md` and issue comments write `SYS-01` (or `SYS-01 (#2)` when the link matters); the commit *footer* still needs `Fixes #N` / `Refs #N` for GitHub auto-linking. Current map: SYS-01..07 = #2..#8, OPS-01..03 = #9..#11, SRC-01..08 = #12..#19, DBT-01..05 = #20..#24, tracker #25, SYS-08 = #26, SYS-09 = #27, SYS-10 = #28, DBT-06 = #29, SYS-11 = #30, SYS-12 = #31, SYS-13 = #32, SYS-14 = #33, DBT-07 = #34, SYS-15 = #36, SYS-16..22 = #37..#43, DBT-09..16 = #44..#51, OPS-04..07 = #52..#55. (#35 was a duplicate of SYS-10, closed.)
- **Bug:** labels `bug` + one severity (`P0 - critical` silent data loss / nothing produced · `P1 - high` systemic · `P2 - medium` single source · `P3 - low` hygiene) + one area (`area: pipeline` / `area: observability` / `area: scraper` / `area: tech-debt`). Body: Where (`file:line`) · Symptom · Root cause · Evidence · Fix · Done when. Template: `.github/ISSUE_TEMPLATE/bug.md`.
- **Requirement / improvement:** labels `enhancement` + area. Body: Motivation · Proposal · Done when. Template: `.github/ISSUE_TEMPLATE/requirement.md`.
- If you discover a bug while working on something else, file it, tell the user the number, and keep going on the original task unless the new bug blocks it.
- The 2026-09-15 audit is tracked in #25 (findings #2–#24, label `audit-2026-09-15`); the full write-up is `AUDIT_2026-09-15.md`. Scraper fixes should be re-verified with `scripts/check_crawlers.py --website <NAME>` and the resulting health line pasted into the issue before closing.

## Workflow: log every experiment

Whenever you probe a site, test a hypothesis, try an approach that might not work, benchmark, or compare options, add an entry to **`EXPERIMENTS.md`** in the same session — succeeded, failed, or inconclusive. Failed experiments are the most valuable entries.

- Read the **"Traps & settled questions"** section at the top of `EXPERIMENTS.md` before starting any scraper or pipeline investigation; it lists what has already been ruled out.
- Entry format is at the top of the file: date + title · Question/hypothesis · Method (exact command or `scripts/experiments/` path) · Result (numbers, exact errors) · Conclusion / do-not-repeat · Links (issue #, commit).
- Reusable diagnostics go in `scripts/experiments/` (e.g. `probe_sitemap_ua.py`); throwaway repro code is inlined in the entry, not left in a scratchpad.
- When a conclusion changes the default approach, add a one-liner to "Traps & settled questions" pointing at the entry.
- Commit the log entry with the related work (`Refs #N`).

## Environment & commands

Windows, PowerShell. Python 3.9 venv at `venv/`. **Always use the venv interpreter**; `requirements.txt` is stale (missing langchain, faiss, google-genai, fastapi, …) — the venv is the source of truth for dependencies.

```powershell
# Tests (unit tests need no DB or network)
venv\Scripts\python.exe -m pytest tests/unit -q
venv\Scripts\python.exe -m pytest tests/unit/test_chunker_helpers.py -q
venv\Scripts\python.exe -m pytest "tests/unit/test_save_chunk_data.py::TestSaveChunkData::test_mixed_new_and_already_embedded" -q

# Integration tests: need local Postgres on port 5431 with a `newsaggregator_test` DB.
# tests/integration/conftest.py force-overrides POSTGRES_* env vars to that DB — never point them at `newsaggregator`.
venv\Scripts\python.exe -m pytest tests/integration -q

# Run a crawl over the HEALTHY list in __main__.py (override: CRAWL_WEBSITES=KOMPAS,CNBC CRAWL_TASK=sitemap), or dispatch a task directly:
venv\Scripts\python.exe __main__.py
venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from newscrawler.application.api.lambda_function import lambda_handler; lambda_handler.process_event({'task': 'all', 'website': 'BISNIS,KOMPAS'}, None)"

# Other tasks: 'sitemap', 'full_text', 'all', 'extract_knowledge' (needs GEMINI_API_KEY), 'newsletter'

# RAG web UI
venv\Scripts\python.exe -m uvicorn newscrawler.web.app:app --port 8000

# Knowledge-base CLI
venv\Scripts\python.exe -m newscrawler.tools.kb_query --ticker BBCA --days 30

# Crawler health check (real code paths, tiny sample per outlet; exit 1 if any unhealthy; writes crawler_health/<date>.json)
venv\Scripts\python.exe scripts/check_crawlers.py --website KOMPAS,DETIK --sample-size 2

# Re-crawl sitemaps that have no article row
venv\Scripts\python.exe scripts/backfill_missing_articles.py --website WARTAEKONOMI

# Schema migrations (hand-written SQL, run once, in this order on a fresh DB)
psql -U postgres -d newsaggregator -f scripts/migrate_phase1.sql
psql -U postgres -d newsaggregator -f scripts/migrate_articles_columns.sql
psql -U postgres -d newsaggregator -f scripts/migrate_sitemap_crawl_attempt.sql
psql -U postgres -d newsaggregator -f scripts/migrate_phase2.sql   # entities, entity_aliases, entity_mentions, api_usage_log
psql -U postgres -d newsaggregator -f scripts/migrate_phase3.sql   # newsletter_digests
psql -U postgres -d newsaggregator -f scripts/migrate_phase4.sql
psql -U postgres -d newsaggregator -f scripts/migrate_phase5.sql   # crawl_log
```

Known-broken test: `tests/test_agents.py` imports `newscrawler.agents`, which no longer exists — it fails at collection. Run `tests/unit` / `tests/integration` explicitly rather than bare `pytest`.

`.pre-commit-config.yaml` (black, flake8 `--max-line-length=120`, bandit) exists but pins Python 3.7-era hooks and is not wired up in the venv; don't rely on it.

## Configuration

All settings are read from env vars in `newscrawler/core/constants.py` **at import time**, so `load_dotenv()` must run before any `newscrawler` import (`__main__.py`, `web/app.py`, and the `scripts/*.py` all do this). The `.env` file at the repo root is the live config (gitignored). Defaults worth knowing: Postgres is `localhost:5431/newsaggregator` (non-standard port), `SITEMAP_RECRAWL_COOLDOWN_DAYS=7`, `DAILY_API_CALL_LIMIT=1400` Gemini calls, `PARALLELIZE` is hard-coded `True`, `MAX_WORKER` controls the thread pool.

## Architecture

Layered (clean-architecture style). Dependencies point inward: `application/api` → `domain/services` → `domain/repositories` (abstract) ← `infrastructure/repositories` (impl) → `infrastructure/datasource` (SQLAlchemy, FAISS, scrapers).

### Wiring & dispatch

`lambda_handler.process_event(event, ctx)` is the single entry point for every task. `init_crawler()` builds `SQLAlchemyClient → DataFlowRepositoryImpl → CrawlerServiceImpl(chunker) → CrawlerAPI`; `CrawlerAPI.crawl_website` switches on `event["task"]`. Note `process_event` catches `BaseException` and logs it at INFO — failures are effectively silent at the top level; check the `crawl_log` table (`status`, `error_msg`) instead.

`DataFlowRepositoryImpl` is the composition root for infrastructure: it owns `NewsDataSource` (sitemaps + articles SQL), `ChunkFAISSDatasource`, `SQLAlchemyChunkDataSource`, `KnowledgeExtractor`, and `NewsletterGenerator`. Constructing it loads the sentence-transformers model and both FAISS indexes, so it is slow (~10s+) — the web app lazily builds these singletons on first request.

### The crawl pipeline (`task=all`) — `CrawlerServiceImpl`

1. **Sitemap crawl** (`crawl_sitemaps`): `Crawler.get_news_in_bulk()` fetches the site's sitemap index, `_get_branches(soup)` picks the news sub-sitemaps, `_scrape()` reads each `<url>` entry (`loc`, `news:title`, `news:publication_date`, `news:keywords`) into dicts → `SitemapDTO`s → `save_sitemap_data`. Dedup key is `(link, posted_at)` where `posted_at` is stored as an **int `yyyymmdd`**, not a timestamp. `save_sitemaps` returns DTOs with `sitemap_id` populated (DTOs are frozen pydantic dataclasses, so it uses `dataclasses.replace`) and the service passes those directly into step 2.
2. **Article crawl** (`crawl_newsdetails`): per batch, `batch_crawling_details` runs `_get_news_details` in a `ThreadPoolExecutor` (serial only for MEDIAINDONESIA). Text extraction is site-specific `_get_whole_text(soup)` → trafilatura fallback → newspaper3k fallback. Then, in order:
   - `mark_sitemaps_attempted()` stamps `sitemaps.last_crawl_attempt` for every successfully-extracted sitemap so it leaves the queue for the cooldown window (extraction failures stay eligible for retry).
   - `SemanticImportanceFilter.is_important(title + first 500 chars)` — cosine similarity vs. the `INTERESTS` keyword list (threshold 0.35). Articles failing this are **never saved**; this is by design.
   - `HierarchicalChunker.chunk()` → L1 chunk (first two paragraphs, for clustering) + L2 paragraph chunks (80–450 whitespace tokens, 50 overlap, for RAG/extraction).
   - `save_chunk_data`: embeds into the `NEWS_L1/` and `NEWS_L2/` FAISS directories (LangChain FAISS + HuggingFace `paraphrase-multilingual-MiniLM-L12-v2`, normalized). FAISS dedups by `sitemap_id` found in the docstore; already-embedded chunks come back with `embedding_id=None` and are *not* re-inserted into the SQL `chunks` table, but their `sitemap_id`s *are* still returned so the article row gets saved.
   - `save_newsdetails_data` → `articles` row (`meta_data.posted_at` also converted to int `yyyymmdd`).

The article-crawl queue (`load_all_sitemaps`) = sitemaps with no `articles` row AND (`last_crawl_attempt` IS NULL OR older than `SITEMAP_RECRAWL_COOLDOWN_DAYS`), newest first, limited to 1000. Both the cooldown stamp and the "return all sitemap_ids from FAISS" behaviour were bug fixes for a "thousands of sitemaps, no articles" gap — don't regress them (covered by `tests/unit/test_mark_attempted_wiring.py` and `test_save_chunk_data.py`).

### Downstream phases

- **Knowledge extraction** (`core/knowledge_extractor.py`): Gemini (`google.genai` client, `GEMINI_MODEL`) extracts persons/orgs/locations/event_type per article, `EntityNormalizer` + `entity_aliases` map names to canonical entities, results go to `entities` / `entity_mentions`, and `articles.knowledge_extracted` is flipped. Daily call count is tracked in `api_usage_log` and hard-stopped at `DAILY_API_CALL_LIMIT`. Silently no-ops if `GEMINI_API_KEY` is unset.
- **Newsletter** (`core/newsletter_generator.py`): DBSCAN over L1 embeddings for a date → clusters → summaries → `digests/YYYY-MM-DD.md` + `newsletter_digests` row.
- **RAG web UI** (`web/`): FastAPI + Jinja templates. `QueryProcessor` does hybrid retrieval — FAISS L2 semantic (L2 distance converted to cosine in `search_l2`), Postgres FTS on `chunks.fts_vector`, and recency, weighted by `RAG_*_WEIGHT` constants — then answers with Gemini.

### Site crawlers

Each outlet is a `Crawler` subclass in `infrastructure/datasource/scrapers/<site>/`. Registering a new one requires touching **four** places: `WebsiteName` enum, `URL` enum (`domain/entities/extraction/`), `CRAWLER_DICT` (`core/crawler_dict_list.py`) and `WEB_URL_DICT` (`core/crawler_url_list.py`). `CRAWLER_DICT` instantiates every crawler at import time. A subclass sets `website_name`/`website_url` and implements `_get_branches`, `_get_whole_text`, `_get_reporter_from_text`; override `_scrape`/`_get_link` only when the sitemap deviates from the standard Google-news format. The base `_get_link` appends `?page=all` to every URL except JPNN. Body extractors should run paragraph text through `core/utils/utils.py:preprocess_text` and drop "Baca juga"-style boilerplate.

Many crawlers rot as sites change; as of 2026-06-02 only 13/32 were healthy. Use `scripts/check_crawlers.py --website <NAME>` to verify a scraper before and after changing it.

### Database schema

Tables: `sitemaps`, `articles`, `chunks`, `entities`, `entity_aliases`, `entity_mentions`, `api_usage_log`, `newsletter_digests`, `crawl_log`. The schema is owned by the SQL files in `scripts/migrate_*.sql` — `Base.metadata.create_all` is never called. The SQLAlchemy models in `infrastructure/datasource/dataflow/write/sqlalchemy/table.py` and `knowledge_table.py` must be kept in sync by hand; several past outages were `DatatypeMismatch` errors from drift between the two (e.g. `is_embedded` int vs bool). Most reads are raw `text()` SQL built from `Table.column.name`, not ORM queries.
