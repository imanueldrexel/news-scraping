# Product Requirements Document
## NewsAggregator — Knowledge Base, Newsletter & RAG Search Platform

**Version:** 1.0  
**Date:** 2026-05-21  
**Author:** imanueldrexel  
**Status:** Draft

---

## Table of Contents

1. [Background & Motivation](#1-background--motivation)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [User Stories](#4-user-stories)
5. [System Architecture Overview](#5-system-architecture-overview)
6. [Chunking Strategy (Foundation)](#6-chunking-strategy-foundation)
7. [Updated Data Pipeline](#7-updated-data-pipeline)
8. [Database Schema](#8-database-schema)
9. [Product A — Emiten Knowledge Base](#9-product-a--emiten-knowledge-base)
10. [Product B — Newsletter Digest](#10-product-b--newsletter-digest)
11. [Product C — RAG Search Web UI](#11-product-c--rag-search-web-ui)
12. [Tech Stack & Cost](#12-tech-stack--cost)
13. [Build Phases & Milestones](#13-build-phases--milestones)
14. [Non-Functional Requirements](#14-non-functional-requirements)
15. [Risks & Mitigations](#15-risks--mitigations)
16. [Future Scope](#16-future-scope)

---

## 1. Background & Motivation

The existing system scrapes news from 33 Indonesian news portals (Detik, Kompas, CNBC Indonesia, Bisnis Indonesia, Kontan, etc.) twice daily. Articles are stored in PostgreSQL and embedded into a local FAISS vector index using Ollama (`nomic-embed-text`). The semantic importance filter ensures only finance/economy-related articles are persisted.

Currently the pipeline terminates at storage — the data has no user-facing product on top of it. The raw collection is valuable but underutilized:

- **For research:** Tracking what stories surround a specific emiten (IDX-listed company) requires manual querying
- **For awareness:** There is no automated digest to stay informed about macroeconomic or capital market developments
- **For retrieval:** There is no interface to ask natural-language questions against the accumulated news corpus

Additionally, the current embedding approach (one embedding per whole article, generated via sequential HTTP calls to a local Ollama instance) creates a processing bottleneck and produces low-quality vectors for long articles.

This PRD defines the requirements to:
1. Fix the embedding pipeline (chunking + Ollama replacement)
2. Build three downstream products on top of the improved data

---

## 2. Problem Statement

### 2.1 Pipeline Problems

| Problem | Impact |
|---|---|
| Whole-article single embedding | Semantic precision degrades for articles > 400 tokens; important facts in later paragraphs are diluted |
| Sequential Ollama HTTP calls | Each article waits for local Ollama to respond; 100 articles = 100 round-trips; cannot be batched efficiently |
| No chunk-level indexing | RAG retrieval returns whole articles instead of the specific paragraph with the answer |
| No knowledge extraction step | Entities, events, metrics are buried as unstructured text; cannot be queried structurally |

### 2.2 Product Gap

There is no output layer. The data sits in PostgreSQL and FAISS but is not accessible to any user or downstream consumer. Three concrete needs are unmet:

1. **Research need:** *"What have news portals reported about BBCA (Bank Central Asia) in the last 30 days, and who are the key people mentioned?"* — currently requires raw SQL
2. **Awareness need:** *"What are the 5 most important Indonesian economic/capital market stories today?"* — currently zero automation
3. **Query need:** *"What is the latest news on Indonesian government bonds?"* — currently requires manual browsing

---

## 3. Goals & Non-Goals

### Goals

- Replace Ollama embedding bottleneck with in-process `sentence-transformers` batching
- Implement hierarchical chunking (article-level + paragraph-level) for all ingested articles
- Build a structured knowledge base of entities (Person, Organization, Location) and their news mentions, focused on Indonesian emiten and capital market actors
- Produce a daily markdown digest suitable for ingestion by the openclaw bot
- Provide a simple web UI for RAG-based question answering over the news corpus

### Non-Goals (MVP)

- Real-time or streaming crawl (twice-daily batch is sufficient)
- Relationship/graph extraction between entities (post-MVP)
- Multi-language support beyond Bahasa Indonesia and English
- User authentication or multi-user access control on the RAG UI
- Mobile app or push notifications
- Email delivery of newsletters (markdown file only for now)
- Fine-tuned LLM for Indonesian financial domain (use general models)
- IDX price data integration (news only)

---

## 4. User Stories

### Product A — Knowledge Base

| ID | As a... | I want to... | So that... |
|---|---|---|---|
| KB-1 | Researcher | Search for an emiten by ticker or name | I can see all news articles mentioning that company |
| KB-2 | Researcher | Filter mentions by date range and category | I can focus on recent or period-specific stories |
| KB-3 | Researcher | See which people (executives, ministers) are associated with an emiten | I can understand key actors in a company's news story |
| KB-4 | Researcher | See which events recur around an entity | I can identify patterns (e.g., "BBRI mentioned in BI rate announcements 4x this month") |
| KB-5 | Researcher | Export entity mentions as a CSV or JSON | I can do further offline analysis |

### Product B — Newsletter

| ID | As a... | I want to... | So that... |
|---|---|---|---|
| NL-1 | User | Receive a daily markdown digest | I stay informed without reading 33 news portals |
| NL-2 | User | See stories grouped by topic cluster | I don't read the same story 5 times from different sources |
| NL-3 | User | See bullet-point summaries per cluster | I can skim the key facts quickly |
| NL-4 | openclaw bot | Ingest the markdown digest as context | It can answer questions about today's news with source attribution |
| NL-5 | User | See how many sources reported each story | I can gauge the importance of each cluster |

### Product C — RAG Search

| ID | As a... | I want to... | So that... |
|---|---|---|---|
| RAG-1 | User | Type a natural language question | I get a direct answer instead of a list of links |
| RAG-2 | User | See which articles and chunks were used to answer | I can verify the answer and trace sources |
| RAG-3 | User | Filter by date range before querying | I can ask about a specific period |
| RAG-4 | User | See the answer in Bahasa Indonesia if I ask in Indonesian | The system respects my query language |
| RAG-5 | User | Ask follow-up questions in a session | I can narrow down the answer without re-querying from scratch |

---

## 5. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER (existing)                    │
│                                                                       │
│  Schedule (2x/day)                                                    │
│      ↓                                                                │
│  lambda_handler / __main__                                            │
│      ↓                                                                │
│  CrawlerAPI → CrawlerServiceImpl                                      │
│      ↓                           ↓                                   │
│  Phase 1: Sitemap crawl     Phase 2: Article detail crawl             │
│      ↓                           ↓                                   │
│  PostgreSQL: sitemaps        SemanticImportanceFilter                 │
│                                  ↓                                   │
│                          PostgreSQL: articles                         │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PROCESSING LAYER (new)                            │
│                                                                       │
│  HierarchicalChunker                                                  │
│      ↓                   ↓                                           │
│  L1: article summary    L2: paragraph chunks (200–400 tok)           │
│      ↓                   ↓                                           │
│  SentenceTransformer.encode() [batched, in-process]                  │
│      ↓                   ↓                                           │
│  FAISS L1 index         FAISS L2 index                               │
│      ↓                   ↓                                           │
│  PostgreSQL: chunks table (text + metadata)                          │
│      ↓                                                               │
│  LLM Entity Extractor (Gemini Flash free tier)                       │
│      ↓                                                               │
│  PostgreSQL: entities, entity_mentions tables                         │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
          ┌─────────────┐  ┌──────────────┐  ┌───────────────┐
          │  Product A  │  │  Product B   │  │   Product C   │
          │  Knowledge  │  │  Newsletter  │  │  RAG Search   │
          │    Base     │  │   Digest     │  │   Web UI      │
          │ (Internal   │  │ (Markdown →  │  │  (FastAPI +   │
          │   Tool)     │  │ openclaw bot)│  │   React/HTML) │
          └─────────────┘  └──────────────┘  └───────────────┘
```

---

## 6. Chunking Strategy (Foundation)

This is the most critical architectural change. All three products depend on high-quality chunking.

### 6.1 Current State (Problem)

```
Article (avg 800–1500 words)
    └── 1 embedding → 1 FAISS entry
```

**Failure modes:**
- A 1500-word article about BBCA is stored as a single 768D vector that averages all topics discussed
- A paragraph about BI rate decision buried at position 6 cannot be retrieved independently
- Entity extraction on a 1500-word blob produces lower-precision results than on a single focused paragraph

### 6.2 Proposed: Hierarchical (Parent-Child) Chunking

```
Article
 ├── [L1] Article-level summary chunk
 │     → 1 embedding per article
 │     → Used for: topic clustering (newsletter), broad topic routing (RAG)
 │
 └── [L2] Paragraph-level chunks (N per article)
       → 1 embedding per chunk
       → Used for: precise evidence retrieval (RAG), entity extraction (KB)
       → Chunk size: 200–400 tokens
       → Overlap: 50 tokens between adjacent chunks
```

### 6.3 Chunking Rules

**Step 1 — Split at natural paragraph boundaries**
- Use `\n\n` or `\n` as primary split signal
- Preserve sentence integrity — never split mid-sentence

**Step 2 — Size normalization**
| Condition | Action |
|---|---|
| Chunk < 80 tokens | Merge with next paragraph |
| Chunk > 450 tokens | Split further with 50-token sentence-aware overlap |
| Single sentence paragraph | Keep as-is if ≥ 30 tokens |
| Article has < 2 chunks after splitting | Keep as single L2 chunk (very short articles) |

**Step 3 — L1 summary chunk**
- Option A (simple): Use the first 2 paragraphs as the L1 chunk (news lede)
- Option B (better): LLM-generated 3-sentence summary
- **MVP recommendation: Option A** — cheaper, deterministic, news articles front-load the key info

### 6.4 Metadata Per Chunk

Every chunk (L1 and L2) carries the following metadata. This is what makes retrieval powerful.

```python
{
    "chunk_id":       int,         # PK
    "sitemap_id":     int,         # FK → sitemaps
    "article_id":     int,         # FK → articles
    "chunk_level":    int,         # 1 = article summary, 2 = paragraph
    "chunk_index":    int,         # 0-based position in article
    "chunk_total":    int,         # total L2 chunks in this article
    "is_first_chunk": bool,        # True if chunk_index == 0
    "is_last_chunk":  bool,
    "text_content":   str,         # raw text of this chunk
    "title":          str,         # parent article headline
    "source":         str,         # e.g., "KOMPAS"
    "category":       str,         # e.g., "ekonomi"
    "posted_at":      date,        # article publication date
    "reporter":       list[str],   # author(s)
    "token_count":    int,         # approximate token count
    "embedding_id":   str,         # FAISS doc ID reference
}
```

### 6.5 Embedding Replacement: Ollama → SentenceTransformer

**Remove:** `OllamaEmbeddings` (HTTP round-trip to `localhost:11434` per article)

**Replace with:** `SentenceTransformer("nomic-embed-text")` called in-process

```python
# Before (sequential, 1 HTTP call per article)
for article in articles:
    embedding = ollama_client.embed(article.text)   # blocks

# After (batched, in-process, ~10-50x faster)
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("nomic-embed-text")
texts = [chunk.text_content for chunk in all_chunks]
embeddings = model.encode(texts, batch_size=64, show_progress_bar=True)
```

**Compatibility:** `nomic-embed-text` produces 768D vectors — the existing FAISS index dimension is preserved. No re-indexing required for future articles; existing articles can be re-indexed in a one-time migration job.

**First-run behavior:** Model download ~250MB on first call, then cached locally. No internet needed for subsequent runs.

---

## 7. Updated Data Pipeline

### 7.1 Phase Overview

```
Phase 1:  Sitemap crawl         (unchanged)
Phase 2:  Article crawl         (unchanged)
Phase 3:  Chunking              (NEW)
Phase 4:  Embedding             (CHANGED — replace Ollama)
Phase 5:  Knowledge Extraction  (NEW)
Phase 6:  Newsletter Job        (NEW, scheduled)
```

### 7.2 Phase 1 — Sitemap Crawl (Unchanged)

- Triggered: twice daily (e.g., 06:00 WIB and 18:00 WIB)
- Output: `sitemaps` table rows (headline, link, category, date, keywords)
- Deduplication: composite key `(link, posted_at)`

### 7.3 Phase 2 — Article Crawl (Unchanged)

- Input: `sitemaps WHERE sitemap_id NOT IN articles`
- Processing: site-specific HTML extraction → trafilatura fallback → newspaper3k fallback
- Filter: `SemanticImportanceFilter` (cosine similarity ≥ 0.35 vs. INTERESTS keywords)
- Output: `articles` table rows (full text, reporter, metadata)

### 7.4 Phase 3 — Chunking (NEW)

```
Input:  articles table (new rows since last chunk run)
        
For each article:
    1. Retrieve extracted_text
    2. HierarchicalChunker.chunk(text, metadata)
       ├── Generate L1 chunk (first 2 paragraphs)
       └── Generate L2 chunks (paragraph-level, 200-400 tok, 50 tok overlap)
    3. Write chunk records to chunks table
    4. Track chunk_status = 'pending_embedding'

Output: chunks table (text_content, metadata, embedding_id=NULL)
```

### 7.5 Phase 4 — Embedding (CHANGED)

```
Input:  chunks WHERE embedding_id IS NULL

Processing:
    1. Load SentenceTransformer("nomic-embed-text") — cached after first run
    2. Batch all pending chunk texts (batch_size=64)
    3. model.encode(texts) → numpy array of 768D vectors
    4. FAISS index: separate index for L1 and L2
       ├── faiss_l1.index  ← article summary embeddings
       └── faiss_l2.index  ← paragraph chunk embeddings
    5. Update chunks.embedding_id with FAISS doc IDs
    6. Update chunks.chunk_status = 'embedded'

Output:
    - FAISS L1 index updated
    - FAISS L2 index updated  
    - chunks.embedding_id populated
```

### 7.6 Phase 5 — Knowledge Extraction (NEW)

```
Input:  articles WHERE knowledge_extracted = FALSE

For each article (batched, max 50/run to stay within Gemini free tier):
    
    LLM Prompt (Gemini 1.5 Flash):
    ┌──────────────────────────────────────────────────────────────┐
    │ Extract entities from the following Indonesian news article.  │
    │ Return JSON with this schema:                                  │
    │ {                                                              │
    │   "persons": [{"name": str, "role": str}],                   │
    │   "organizations": [{"name": str, "type": str,               │
    │                       "ticker": str|null}],                   │
    │   "locations": [{"name": str, "type": str}],                 │
    │   "event_type": str,   // e.g. "earnings", "policy",        │
    │                        //       "merger", "appointment"       │
    │   "key_metrics": [{"metric": str, "value": str}]             │
    │ }                                                              │
    │ Article: {article_text}                                        │
    └──────────────────────────────────────────────────────────────┘
    
    Post-processing:
    ├── Normalize entity names (e.g., "BCA" → "Bank Central Asia")
    ├── Resolve ticker symbols (e.g., "BBCA" → entity lookup)
    ├── Upsert into entities table (dedup by normalized name + type)
    ├── Insert into entity_mentions table
    └── Update articles.knowledge_extracted = TRUE

Output: entities, entity_mentions tables populated
```

**Gemini Free Tier Budget:**
- Free tier: 1,500 req/day (Gemini 1.5 Flash)
- 2 crawls/day × avg 50 new articles/crawl = ~100 articles/day
- Well within free tier. Safety margin: implement a daily counter with hard stop at 1,400 req/day.

### 7.7 Phase 6 — Newsletter Job (NEW, Scheduled)

```
Trigger: Daily at 07:00 WIB (after morning crawl completes)

Input:  
    - L1 embeddings from articles posted_at = today (or last 24h)
    - articles + sitemaps metadata for those articles

Processing:
    1. Load L1 FAISS vectors for today's articles
    2. Cluster using DBSCAN (eps=0.25, min_samples=2)
       ├── Each cluster = one news event/topic
       └── Noise points (singleton articles) → "Other News" section
    3. Per cluster:
       ├── Rank articles by source authority score
       │   (Bisnis Indonesia > Kontan > Kompas > others — configurable)
       ├── Deduplicate: keep top-3 most informative sources
       ├── Collect: headlines + L1 chunk texts
       └── LLM summarize (Gemini 1.5 Flash):
           ┌────────────────────────────────────────────────────────┐
           │ Summarize the following news cluster in 3-5 bullet     │
           │ points in the same language as the articles.           │
           │ Focus on: what happened, who is involved, key numbers. │
           │ Articles: {article_texts}                              │
           └────────────────────────────────────────────────────────┘
    4. Assign cluster to category:
       ├── macroeconomics (BI rate, inflation, GDP, APBN)
       ├── capital_market (IDX, stocks, IPO, rights issue)
       ├── banking (OJK, bank earnings, NPL, CAR)
       ├── corporate (M&A, earnings, management changes)
       ├── commodities (CPO, coal, nickel, oil)
       └── other
    5. Generate markdown digest
    6. Save to: /digests/YYYY-MM-DD.md
    7. Insert into newsletter_digests table

Output: /digests/YYYY-MM-DD.md
```

**Markdown digest format:**
```markdown
# Rangkuman Berita — 21 Mei 2026

> Dibuat otomatis dari 33 portal berita Indonesia | 07:00 WIB

---

## 📊 Makroekonomi

### BI Pertahankan Suku Bunga di 6.25%
- Bank Indonesia mempertahankan suku bunga acuan di level 6,25% pada RDG Mei 2026
- Keputusan ini sejalan dengan ekspektasi pasar dan upaya menjaga stabilitas rupiah
- Gubernur BI Perry Warjiyo menyebut inflasi domestik masih terkendali di kisaran 2,8%
- Rupiah menguat 0,3% pasca pengumuman ke level Rp15.820/USD

**Sumber (5 portal):** Bisnis Indonesia · Kompas · CNBC Indonesia · Kontan · Detik
**Artikel terkait:** [Bisnis Indonesia, 21 Mei](link) · [Kompas, 21 Mei](link)

---

## 🏦 Perbankan

### [cluster headline]
- ...

---

## 📈 Pasar Modal

### [cluster headline]
- ...

---

## 🏭 Korporasi

### [cluster headline]
- ...

---

## 🛢️ Komoditas

### [cluster headline]
- ...

---

## 📰 Berita Lainnya

- [headline] — [source] · [date]
- [headline] — [source] · [date]

---
*Total artikel hari ini: 87 | Cluster teridentifikasi: 12 | Dihasilkan: 07:02 WIB*
```

---

## 8. Database Schema

### 8.1 New Tables

```sql
-- ─────────────────────────────────────────────────
-- CHUNKS TABLE
-- Stores all text chunks (L1 summary + L2 paragraphs)
-- ─────────────────────────────────────────────────
CREATE TABLE chunks (
    chunk_id        BIGSERIAL PRIMARY KEY,
    sitemap_id      BIGINT NOT NULL REFERENCES sitemaps(sitemap_id),
    article_id      BIGINT NOT NULL REFERENCES articles(articles_id),
    chunk_level     SMALLINT NOT NULL CHECK (chunk_level IN (1, 2)),
    chunk_index     INT NOT NULL DEFAULT 0,
    chunk_total     INT NOT NULL DEFAULT 1,
    is_first_chunk  BOOLEAN NOT NULL DEFAULT FALSE,
    is_last_chunk   BOOLEAN NOT NULL DEFAULT FALSE,
    text_content    TEXT NOT NULL,
    token_count     INT,
    embedding_id    TEXT,               -- FAISS document ID
    chunk_status    TEXT NOT NULL DEFAULT 'pending_embedding'
                    CHECK (chunk_status IN ('pending_embedding', 'embedded', 'failed')),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_sitemap_id ON chunks(sitemap_id);
CREATE INDEX idx_chunks_article_id ON chunks(article_id);
CREATE INDEX idx_chunks_level ON chunks(chunk_level);
CREATE INDEX idx_chunks_status ON chunks(chunk_status);

-- ─────────────────────────────────────────────────
-- ENTITIES TABLE
-- Normalized entity registry (deduped by name+type)
-- ─────────────────────────────────────────────────
CREATE TABLE entities (
    entity_id       BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,          -- lowercase, no punctuation
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('PERSON', 'ORGANIZATION', 'LOCATION')),
    subtype         TEXT,                   -- e.g. 'emiten', 'ministry', 'central_bank'
    ticker          TEXT,                   -- IDX ticker if applicable (e.g. 'BBCA')
    first_seen_at   DATE,
    last_seen_at    DATE,
    mention_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (normalized_name, entity_type)
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_ticker ON entities(ticker);
CREATE INDEX idx_entities_normalized ON entities(normalized_name);

-- ─────────────────────────────────────────────────
-- ENTITY_MENTIONS TABLE
-- Maps entities to the articles that mention them
-- ─────────────────────────────────────────────────
CREATE TABLE entity_mentions (
    mention_id      BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(entity_id),
    sitemap_id      BIGINT NOT NULL REFERENCES sitemaps(sitemap_id),
    article_id      BIGINT NOT NULL REFERENCES articles(articles_id),
    chunk_id        BIGINT REFERENCES chunks(chunk_id),   -- most relevant chunk
    context_snippet TEXT,                                   -- ~200 char window around mention
    event_type      TEXT,                                   -- earnings / policy / appointment / etc.
    posted_at       DATE NOT NULL,
    source          TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, sitemap_id)                         -- one mention record per entity per article
);

CREATE INDEX idx_mentions_entity_id ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_posted_at ON entity_mentions(posted_at);
CREATE INDEX idx_mentions_source ON entity_mentions(source);
CREATE INDEX idx_mentions_event_type ON entity_mentions(event_type);

-- ─────────────────────────────────────────────────
-- NEWSLETTER_DIGESTS TABLE
-- Daily digest records
-- ─────────────────────────────────────────────────
CREATE TABLE newsletter_digests (
    digest_id       BIGSERIAL PRIMARY KEY,
    digest_date     DATE NOT NULL UNIQUE,
    file_path       TEXT NOT NULL,          -- path to .md file on disk
    cluster_count   INT NOT NULL DEFAULT 0,
    article_count   INT NOT NULL DEFAULT 0,
    categories      JSONB,                  -- {"macroeconomics": 3, "banking": 2, ...}
    source_ids      JSONB,                  -- list of sitemap_ids included
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    generation_ms   INT                     -- how long generation took
);
```

### 8.2 Modified Tables

```sql
-- Add to articles table:
ALTER TABLE articles ADD COLUMN knowledge_extracted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE articles ADD COLUMN knowledge_extracted_at TIMESTAMP;

-- Add to sitemaps table (optional, for newsletter dedup):
ALTER TABLE sitemaps ADD COLUMN cluster_id INT;    -- assigned during newsletter job
```

### 8.3 Full-Text Search Setup (for hybrid RAG retrieval)

```sql
-- Enable full-text search on chunks
ALTER TABLE chunks ADD COLUMN fts_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('indonesian', text_content)) STORED;

CREATE INDEX idx_chunks_fts ON chunks USING GIN(fts_vector);

-- Query example:
SELECT chunk_id, text_content, ts_rank(fts_vector, query) AS rank
FROM chunks, to_tsquery('indonesian', 'inflasi & BI') query
WHERE fts_vector @@ query
ORDER BY rank DESC
LIMIT 20;
```

---

## 9. Product A — Emiten Knowledge Base

### 9.1 Description

An internal research tool for querying what news stories surround a specific Indonesian emiten (IDX-listed company) or any tracked entity (person, organization, location). The primary use case is: *"Give me everything the news has said about BBCA this month."*

### 9.2 Interface

**MVP: Command-line / Python script queries against PostgreSQL.**

```bash
# Example usage
python -m newscrawler.tools.kb_query --entity "Bank Central Asia" --days 30
python -m newscrawler.tools.kb_query --ticker "BBCA" --event-type earnings
python -m newscrawler.tools.kb_query --entity "Perry Warjiyo" --from 2026-01-01
```

**Output:** Formatted table + optional JSON/CSV export

```
Entity: Bank Central Asia (BBCA)
Type: ORGANIZATION / emiten
Period: 2026-04-21 → 2026-05-21
Total mentions: 47 articles across 12 portals

DATE        SOURCE              HEADLINE                                    EVENT
2026-05-20  Bisnis Indonesia    BBCA Catat Laba Bersih Rp12T di Q1 2026    earnings
2026-05-19  Kontan              BCA Umumkan Dividen Interim Rp150/Saham      dividend
2026-05-18  CNBC Indonesia      Saham BBCA Melemah 1.2% Ikuti IHSG          market
...

People mentioned alongside: Perry Warjiyo (3x), Jahja Setiaatmadja (8x)
Organizations mentioned alongside: OJK (5x), Bank Indonesia (7x)
Locations: Jakarta (31x), New York (2x)
```

### 9.3 Data Access Patterns

| Query Type | SQL Pattern |
|---|---|
| All articles by emiten ticker | `JOIN entities ON ticker = ? JOIN entity_mentions` |
| Date range filter | `WHERE posted_at BETWEEN ? AND ?` |
| Event type filter | `WHERE event_type = ?` |
| Co-occurring entities | `GROUP BY entity_id WHERE sitemap_id IN (subquery)` |
| Source diversity | `GROUP BY source ORDER BY count DESC` |
| Export | `COPY (SELECT ...) TO STDOUT WITH CSV HEADER` |

### 9.4 Entity Normalization Rules

The LLM extraction will produce varied names for the same entity. Post-processing normalization is required:

| Raw name | Normalized | Ticker |
|---|---|---|
| BCA | Bank Central Asia | BBCA |
| Bank BCA | Bank Central Asia | BBCA |
| PT BCA Tbk | Bank Central Asia | BBCA |
| BI | Bank Indonesia | — |
| Bank Indonesia | Bank Indonesia | — |
| OJK | Otoritas Jasa Keuangan | — |

**Strategy:**
- Maintain a lookup table `entity_aliases` mapping known aliases to canonical entity_id
- On extraction: check alias table first, fallback to fuzzy match by `normalized_name`
- If no match: insert as new entity (manual review queue for cleanup)

### 9.5 Source Authority Scores

Used for ranking mentions in research output:

```python
SOURCE_AUTHORITY = {
    "BISNIS":       1.0,
    "KONTAN":       0.95,
    "INVESTORID":   0.90,
    "CNBC":         0.85,
    "IDXCHANNEL":   0.85,
    "KOMPAS":       0.80,
    "TEMPO":        0.75,
    "DETIK":        0.70,
    "ANTARA":       0.70,
    # others default to 0.50
}
```

---

## 10. Product B — Newsletter Digest

### 10.1 Description

A daily auto-generated markdown file summarizing the most important Indonesian financial/economic news of the day. The file is designed to be passed directly into the openclaw bot as context, enabling it to answer questions like *"What happened in Indonesian markets today?"*

### 10.2 File Output

- **Location:** `{project_root}/digests/YYYY-MM-DD.md`
- **Generated at:** 07:00 WIB daily (after morning crawl at ~06:00 WIB completes)
- **Filename format:** `2026-05-21.md`
- **Encoding:** UTF-8

### 10.3 Clustering Algorithm

```python
# Step 1: Load today's L1 embeddings
vectors = faiss_l1.get_embeddings(today_sitemap_ids)

# Step 2: DBSCAN clustering
from sklearn.cluster import DBSCAN
clustering = DBSCAN(
    eps=0.25,           # cosine distance threshold for same-story
    min_samples=2,      # at least 2 articles to form a cluster
    metric='cosine'
).fit(vectors)

# Step 3: Label = -1 means noise (singleton articles → "Other News")
```

**Tuning notes:**
- `eps=0.25` means articles within 0.25 cosine distance are the "same story"
- Lower eps = more clusters (stricter same-story definition)
- Higher eps = fewer, broader clusters
- Start with 0.25, adjust based on real data quality

### 10.4 Category Assignment

After clustering, assign each cluster to a category using keyword matching on the cluster's article titles:

```python
CATEGORY_KEYWORDS = {
    "macroeconomics": ["inflasi", "suku bunga", "BI rate", "GDP", "PDB", "APBN", "neraca"],
    "capital_market": ["IHSG", "saham", "IDX", "IPO", "rights issue", "emiten", "bursa"],
    "banking":        ["bank", "OJK", "NPL", "CAR", "kredit", "deposito", "fintech"],
    "corporate":      ["akuisisi", "merger", "direksi", "komisaris", "laba", "rugi", "dividen"],
    "commodities":    ["CPO", "sawit", "batu bara", "nikel", "minyak", "gas", "LNG"],
}
```

### 10.5 openclaw Bot Integration

The digest markdown is designed to be injected as a system context block or user message to the openclaw bot. Recommended usage:

```
[System context to openclaw bot]
<news_digest date="2026-05-21">
{contents of 2026-05-21.md}
</news_digest>

User: Apa yang terjadi di pasar saham hari ini?
```

The digest includes article links (where available) so openclaw can cite sources in its answers.

### 10.6 Failure Handling

| Failure | Behavior |
|---|---|
| No articles today (holiday, crawl failed) | Generate digest with "Tidak ada artikel hari ini" notice |
| Gemini API rate limit hit | Use article headlines only (no LLM summary), mark as `summarization_skipped=true` |
| DBSCAN produces 0 clusters | Fall back to category-keyword grouping without clustering |
| Digest generation fails | Log error, retry once, send alert log to `digests/errors.log` |

---

## 11. Product C — RAG Search Web UI

### 11.1 Description

A simple web interface where a user types a natural-language question and receives an answer synthesized from the news corpus, with source citations. The interface supports session-based follow-up questions.

### 11.2 Architecture

```
Browser
  ↓ HTTP POST /api/query
FastAPI backend
  ↓
QueryProcessor
  ├── 1. Embed query with SentenceTransformer
  ├── 2. FAISS L2 search (semantic) → top-20 chunks
  ├── 3. PostgreSQL full-text search (BM25) → top-20 chunks
  ├── 4. Merge + deduplicate → top-40 chunks
  ├── 5. Re-rank by: semantic score × 0.6 + BM25 score × 0.3 + recency × 0.1
  ├── 6. Take top-5 chunks
  ├── 7. Fetch parent article context for each chunk (L1 summary)
  └── 8. LLM answer generation (Gemini 1.5 Flash)
       Prompt: Answer the question using ONLY the provided context.
               Cite sources as [Source, Date].
               If unsure, say so.
               Context: {top5_chunks_with_metadata}
               Question: {user_query}
  ↓
Return: { answer, sources, chunks_used, query_time_ms }
```

### 11.3 UI Components

**Single-page application (HTML + vanilla JS or minimal React)**

```
┌──────────────────────────────────────────────────────────────────┐
│  NewsAggregator Search                              [Filter ▼]   │
├──────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Tanya apa saja tentang berita ekonomi Indonesia...   [→]   │  │
│  └────────────────────────────────────────────────────────────┘  │
│  Date range: [All time ▼]   Category: [All ▼]   Source: [All ▼] │
├──────────────────────────────────────────────────────────────────┤
│  ANSWER                                                           │
│  ─────                                                            │
│  Bank Indonesia mempertahankan suku bunga di 6,25% pada          │
│  rapat Mei 2026 [Bisnis Indonesia, 20 Mei 2026]. Keputusan       │
│  ini didorong oleh inflasi yang masih terkendali [Kompas,        │
│  21 Mei 2026]...                                                  │
│                                                                   │
│  SOURCES USED (3 of 5 retrieved)                                  │
│  ──────────────────────────────                                   │
│  • [Bisnis Indonesia, 20 Mei 2026] "BI Pertahankan Suku Bunga"   │
│    > "...Bank Indonesia memutuskan untuk mempertahankan..."       │
│  • [Kompas, 21 Mei 2026] "Inflasi Mei 2026 Terkendali"           │
│    > "...inflasi month-on-month tercatat 0,18%..."               │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Follow-up question...                                [→]   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 11.4 API Endpoints

```
POST /api/query
    Request:  { query: str, date_from?: str, date_to?: str,
                category?: str, source?: str, session_id?: str }
    Response: { answer: str, sources: [...], query_ms: int,
                session_id: str }

GET  /api/health
    Response: { status: "ok", articles_indexed: int, last_crawl: str }

GET  /api/stats
    Response: { total_articles: int, total_chunks: int,
                total_entities: int, date_range: {...} }
```

### 11.5 Session / Follow-up Support

- Session ID is a UUID generated client-side or on first query
- Backend maintains last 5 Q&A pairs per session in memory (LRU cache, TTL 30 min)
- Follow-up queries include conversation history in the LLM prompt
- No persistent session storage required for MVP

### 11.6 Re-ranking Formula

```python
final_score = (
    semantic_score   * 0.6 +   # FAISS cosine similarity
    bm25_score       * 0.3 +   # PostgreSQL ts_rank normalized
    recency_score    * 0.1     # 1.0 = today, decays by 0.1/week
)
```

### 11.7 Tech Stack for Web UI

| Layer | Choice | Reason |
|---|---|---|
| Backend API | FastAPI | Already Python, async, minimal overhead |
| Frontend | HTML + HTMX or vanilla JS | No build step, simple enough for internal tool |
| Session cache | Python dict (in-memory) | No Redis needed for MVP single-user |
| Deployment | `uvicorn` local | Internal tool, no cloud needed for MVP |

---

## 12. Tech Stack & Cost

### 12.1 Full Stack Summary

| Component | Technology | Cost |
|---|---|---|
| Web scraping | requests + BeautifulSoup + trafilatura | Free |
| Semantic filter | sentence-transformers (existing) | Free |
| Embedding | sentence-transformers `nomic-embed-text` in-process | Free |
| Vector store | FAISS (2 indexes: L1, L2) | Free |
| Relational DB | PostgreSQL | Free (self-hosted) |
| Full-text search | PostgreSQL tsvector | Free (built-in) |
| Clustering | scikit-learn DBSCAN | Free |
| LLM (extraction + summarization + RAG) | Gemini 1.5 Flash API | Free (1,500 req/day) |
| RAG API | FastAPI + uvicorn | Free |
| RAG Frontend | HTML + HTMX | Free |
| Scheduler | Windows Task Scheduler or APScheduler | Free |

**Total infrastructure cost: $0/month** (assuming self-hosted PostgreSQL and local machine)

### 12.2 Gemini Free Tier Budget Analysis

| Use | Calls/Day | Est. Tokens/Call | Daily Total |
|---|---|---|---|
| Knowledge extraction | ~100 articles | ~1,200 | ~120,000 tok |
| Newsletter summarization | ~15 clusters | ~800 | ~12,000 tok |
| RAG answer generation | ~20 queries (est.) | ~3,000 | ~60,000 tok |
| **Total** | **~135 calls** | | **~192,000 tok** |

Free tier limits: 1,500 requests/day, 1,000,000 tokens/day → **well within limits**.

Hard stop guard: implement a daily counter in PostgreSQL; halt Gemini calls if `daily_api_calls >= 1,400`.

### 12.3 Crawl Schedule

| Job | Time (WIB) | Description |
|---|---|---|
| Morning crawl | 06:00 | Sitemap + article crawl |
| Morning processing | 06:30 | Chunking + embedding + knowledge extraction |
| Morning newsletter | 07:00 | Generate daily digest |
| Evening crawl | 18:00 | Sitemap + article crawl |
| Evening processing | 18:30 | Chunking + embedding + knowledge extraction |

---

## 13. Build Phases & Milestones

### Phase 1 — Pipeline Foundation (Week 1–2)
**Goal:** All new articles are chunked and embedded correctly.

- [ ] Implement `HierarchicalChunker` class
- [ ] Create `chunks` table in PostgreSQL
- [ ] Replace `OllamaEmbeddings` with `SentenceTransformer` in-process
- [ ] Create two FAISS indexes (L1, L2)
- [ ] Write chunk embedding pipeline (batch encode → FAISS → update chunks table)
- [ ] Write one-time migration script for existing articles
- [ ] Unit tests for chunking edge cases (very short, very long articles)

**Done when:** 100 new articles are chunked, embedded, and queryable via FAISS L2 index.

---

### Phase 2 — Knowledge Extraction (Week 2–3)
**Goal:** Entities are being extracted and queryable.

- [ ] Create `entities`, `entity_mentions` tables
- [ ] Create `entity_aliases` lookup table with seed data (top 50 emiten + key institutions)
- [ ] Implement `KnowledgeExtractor` using Gemini Flash API
- [ ] Implement entity normalization + alias resolution
- [ ] Implement daily API call counter guard
- [ ] Implement `kb_query` CLI tool
- [ ] Integration test: query "BBCA" → see mentions

**Done when:** Can query an emiten ticker and see date-sorted article mentions with context snippets.

---

### Phase 3 — Newsletter Digest (Week 3–4)
**Goal:** Daily markdown digest is generated and openclaw-ready.

- [ ] Create `newsletter_digests` table
- [ ] Implement DBSCAN clustering on L1 embeddings
- [ ] Implement category assignment from cluster keywords
- [ ] Implement per-cluster LLM summarization
- [ ] Implement markdown digest generator
- [ ] Set up scheduler (twice daily crawl + 07:00 digest generation)
- [ ] Test with 7 days of historical data
- [ ] Validate openclaw bot can ingest the markdown format

**Done when:** Digest is generated daily at 07:00 WIB and openclaw can answer questions from it.

---

### Phase 4 — RAG Search Web UI (Week 4–5)
**Goal:** Working web interface for question answering.

- [ ] Implement `QueryProcessor` (FAISS search + BM25 + merge + re-rank)
- [ ] Implement FastAPI backend with `/api/query` endpoint
- [ ] Implement session management (in-memory, LRU)
- [ ] Build HTML/HTMX frontend
- [ ] Implement source citation in LLM prompt
- [ ] Add date range + category filters
- [ ] End-to-end test: question → answer with sources
- [ ] Performance test: response time < 5s for typical query

**Done when:** Can ask a question in the browser and get a cited answer within 5 seconds.

---

### Phase 5 — Polish & Monitoring (Week 5–6)
**Goal:** System runs reliably unattended.

- [ ] Add daily Gemini API usage logging
- [ ] Add crawl success/failure logging to PostgreSQL
- [ ] Add digest generation health check (alert if digest not generated by 08:00 WIB)
- [ ] Add KB tool CSV/JSON export
- [ ] Add basic stats endpoint to RAG API (`/api/stats`)
- [ ] Documentation: `OPERATIONS.md` (how to run, monitor, troubleshoot)

---

## 14. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Crawl frequency | 2x daily minimum |
| Article processing latency | New article → embedded within 30 min of crawl |
| RAG query response time | < 5 seconds end-to-end (p95) |
| Newsletter generation time | < 5 minutes |
| Embedding throughput | ≥ 200 chunks/minute (SentenceTransformer batched) |
| FAISS index size | Support up to 5M chunks (≈ 3 years of daily crawls) |
| PostgreSQL storage | Estimated 2GB/year (text + metadata, no raw HTML) |
| Gemini API usage | Hard stop at 1,400 req/day |
| System uptime requirement | Best-effort (internal tool, no SLA) |
| Data retention | Indefinite (all articles kept) |

---

## 15. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Gemini API changes free tier limits | Medium | High | Daily counter guard; fallback to extractive summary (no LLM) |
| News portals change HTML structure (scraper breaks) | High | Medium | Site-specific crawlers already isolated; add monitoring for zero-article crawls |
| FAISS index corruption | Low | High | Snapshot FAISS index after each successful embedding run |
| Entity extraction quality low for uncommon emiten | Medium | Medium | Seed entity_aliases table with IDX master list; manual review queue |
| DBSCAN clustering produces poor clusters | Medium | Medium | Tune eps parameter; fallback to category-keyword grouping |
| PostgreSQL disk full | Low | High | Monitor disk usage; add VACUUM schedule; archive old chunks to cold storage |
| SentenceTransformer produces different vectors than Ollama (index compatibility) | High (first run) | Medium | One-time re-embedding of existing articles in migration Phase 1 |

---

## 16. Future Scope

The following are explicitly out of MVP scope but natural next steps:

- **Relationship extraction:** "Company A acquired Company B" → graph edges between entities. Enables network analysis of corporate relationships.
- **Event timeline:** Visual timeline of events per entity across date range.
- **Price correlation:** Overlay IDX price data to correlate news events with stock movements.
- **Alert system:** Notify when a watched emiten is mentioned above a frequency threshold.
- **Email delivery:** Send daily digest via SMTP (once openclaw integration is validated).
- **Multi-language:** English-language news sources (Reuters, Bloomberg Indonesia).
- **Fine-tuned NER:** Indonesian financial domain NER model for higher entity extraction accuracy.
- **Graph database (Neo4j):** Migrate entities/relationships to a graph store for complex multi-hop queries.
- **Microservices split:** Decouple ingestion, processing, and products into separate services (Redis Streams as per existing MICROSERVICES_README.md plan).
- **ChromaDB migration:** Replace FAISS with ChromaDB for easier metadata filtering and persistence.

---

*End of PRD v1.0*
