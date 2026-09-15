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
| 06:00 | Morning crawl | `python __main__.py` (task=all) |
| 06:45 | Knowledge extraction | task=extract_knowledge |
| 07:00 | Newsletter | task=newsletter |
| 18:00 | Evening crawl | task=all |
| 18:45 | Knowledge extraction | task=extract_knowledge |

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

### Check digest generation
```sql
SELECT digest_date, cluster_count, article_count, generation_ms, generated_at
FROM newsletter_digests
ORDER BY digest_date DESC
LIMIT 7;
```
If today's digest is missing after 07:30 WIB, run newsletter task manually.

### Check entity extraction progress
```sql
SELECT
  COUNT(*) FILTER (WHERE knowledge_extracted = 0) AS pending,
  COUNT(*) FILTER (WHERE knowledge_extracted = 1) AS extracted
FROM articles;
```

### API stats endpoint
```
GET http://localhost:8000/api/stats
GET http://localhost:8000/api/health
```

---

## One-Time Setup (first run)

```bash
# 1. Run migrations
psql -U postgres -d newsaggregator -f scripts/migrate_phase2.sql
psql -U postgres -d newsaggregator -f scripts/migrate_phase3.sql
psql -U postgres -d newsaggregator -f scripts/migrate_phase4.sql
psql -U postgres -d newsaggregator -f scripts/migrate_phase5.sql

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
