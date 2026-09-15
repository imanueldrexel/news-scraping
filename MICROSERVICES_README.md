# Indonesian News Scraper - Microservices Architecture

A microservices-based news scraping and knowledge graph system for Indonesian news.

## Architecture Overview

```
News Sources (33 sites)
        │
        ▼
┌─────────────────────┐
│ Service 1: Ingestion│ ──► Redis Stream: stream:ingested
│ (Sitemap + Fetch)   │
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│Service 2: Preprocess│ ──► Redis Stream: stream:preprocessed
│ (Clean + Chunk)     │
└─────────────────────┘
        │
        ├──────────────────────┐
        ▼                      ▼
┌───────────────┐    ┌──────────────────┐
│Service 2.5:   │    │Service 3:        │
│Vectorizer     │    │Extraction Engine │
│(ChromaDB)     │    │(Triplets)        │
└───────────────┘    └──────────────────┘
        │                      │
        ▼                      ▼
┌───────────────┐    ┌──────────────────┐
│Service 6:     │    │Service 4: Entity │
│Analyst        │    │Resolver          │
│(Summarizer)   │    └──────────────────┘
└───────────────┘              │
                               ▼
                    ┌──────────────────┐
                    │Service 5: Graph  │
                    │Store (Neo4j)     │
                    └──────────────────┘
```

## Services

| Service | Purpose | Input Stream | Output Stream |
|---------|---------|--------------|---------------|
| **Ingestion** | Sitemap monitoring, content fetching | - | stream:ingested |
| **Preprocessor** | HTML cleaning, relevance check, chunking | stream:ingested | stream:preprocessed |
| **Vectorizer** | Embedding generation, ChromaDB storage | stream:preprocessed | stream:vectorized |
| **Extraction** | Triplet extraction using LLM | stream:preprocessed | stream:triplets |
| **Entity Resolver** | Indonesian name normalization | stream:triplets | stream:entities |
| **Graph Store** | Neo4j knowledge graph | stream:entities | - |
| **Analyst** | Cluster detection, summarization | stream:vectorized | stream:cluster-summaries |

## Tech Stack

- **Message Queue**: Redis Streams
- **Vector Database**: ChromaDB
- **Graph Database**: Neo4j Community Edition
- **LLM Runtime**: Ollama
- **LLM Models**: qwen2.5:7b-instruct, nomic-embed-text
- **Language**: Python 3.11

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- NVIDIA GPU (recommended for Ollama)
- At least 16GB RAM

### 2. Setup

```bash
# Copy environment file
cp .env.example .env

# Start infrastructure services
docker-compose up -d redis neo4j chromadb ollama postgres

# Wait for services to be ready
sleep 30

# Pull Ollama models
docker-compose exec ollama ollama pull nomic-embed-text
docker-compose exec ollama ollama pull qwen2.5:7b-instruct

# Initialize databases
python scripts/init_chromadb.py
docker-compose exec neo4j cypher-shell -u neo4j -p password123 -f /var/lib/neo4j/import/init_neo4j.cypher

# Start all services
docker-compose up -d
```

### 3. Monitor

```bash
# View logs
docker-compose logs -f ingestion
docker-compose logs -f preprocessor
docker-compose logs -f extraction

# Check Redis Streams
docker-compose exec redis redis-cli XLEN stream:ingested
docker-compose exec redis redis-cli XLEN stream:preprocessed
docker-compose exec redis redis-cli XLEN stream:triplets

# Check Neo4j (browser)
# Open http://localhost:7474
# Login: neo4j / password123
```

## Configuration

Environment variables (`.env`):

```bash
# Database
POSTGRES_USER=news
POSTGRES_PASSWORD=news123

# Neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# Ollama
LLM_MODEL=qwen2.5:7b-instruct
EMBEDDING_MODEL=nomic-embed-text

# Processing
RELEVANCE_THRESHOLD=0.35
FUZZY_THRESHOLD=0.85
SIMILARITY_THRESHOLD=0.85
POLLING_INTERVAL=300
```

## Directory Structure

```
news-scraping/
├── docker-compose.yml
├── .env.example
├── shared/                    # Shared libraries
│   ├── schemas/               # Message schemas
│   ├── redis_client/          # Redis wrapper
│   └── config/                # Settings
├── services/
│   ├── ingestion/             # Service 1
│   ├── preprocessor/          # Service 2
│   ├── vectorizer/            # Service 2.5
│   ├── extraction/            # Service 3
│   ├── entity_resolver/       # Service 4
│   ├── graph_store/           # Service 5
│   └── analyst/               # Service 6
├── scripts/
│   ├── init_neo4j.cypher
│   ├── init_chromadb.py
│   └── pull_models.sh
└── newscrawler/               # Legacy code (reference)
```

## Neo4j Graph Schema

### Node Types
- `Person` - Individual people (canonical_name, aliases, mention_count)
- `Company` - Companies (canonical_name, aliases, sector)
- `Organization` - Non-profit orgs
- `Government` - Government entities
- `Location` - Geographic locations
- `Article` - News articles (url, headline, source, published_at)

### Relationship Types
- `WORKS_FOR` - Employment
- `OWNS` / `OWNED_BY` - Ownership
- `INVESTED_IN` - Investment
- `ACQUIRED` - Acquisition
- `PARTNERED_WITH` - Partnership
- `MENTIONED_IN` - Article mentions
- `APPOINTED_AS` - Position appointments
- `RESIGNED_FROM` - Resignations

## Indonesian Entity Resolution

The Entity Resolver handles Indonesian-specific normalization:

- **Titles removed**: Bapak, Ibu, Pak, Bu, Dr., Prof., H., Hj., etc.
- **Company prefixes**: PT, CV, Tbk standardized
- **Known aliases**:
  - Jokowi → Joko Widodo
  - BCA → PT Bank Central Asia Tbk
  - BI → Bank Indonesia
  - OJK → Otoritas Jasa Keuangan

## Example Queries

### Neo4j Cypher

```cypher
// Find all relationships for a person
MATCH (p:Person {canonical_name: "Joko Widodo"})-[r]->(n)
RETURN type(r), n.canonical_name;

// Find companies mentioned with a person
MATCH (p:Person)-[:MENTIONED_IN]->(a:Article)<-[:MENTIONED_IN]-(c:Company)
WHERE p.canonical_name = "Sri Mulyani Indrawati"
RETURN c.canonical_name, count(a) as articles
ORDER BY articles DESC;

// Get entity network
MATCH path = (e1:Company)-[*1..2]-(e2)
WHERE e1.canonical_name = "PT Bank Central Asia Tbk"
RETURN path LIMIT 50;
```

### ChromaDB Similarity Search

```python
from chromadb import HttpClient

client = HttpClient(host="localhost", port=8000)
collection = client.get_collection("indonesian_news")

# Find similar articles
results = collection.query(
    query_texts=["Bank Indonesia menaikkan suku bunga"],
    n_results=5
)
```

## Scaling

For production, consider:

1. **Horizontal scaling**: Increase `replicas` in docker-compose.yml
2. **GPU allocation**: Configure Ollama with multiple GPUs
3. **Redis clustering**: For high message throughput
4. **Neo4j clustering**: For graph query performance

## Troubleshooting

### Ollama not responding
```bash
docker-compose restart ollama
docker-compose logs ollama
```

### Redis Streams backlog
```bash
# Check pending messages
docker-compose exec redis redis-cli XPENDING stream:ingested group:preprocessor
```

### Neo4j connection issues
```bash
docker-compose exec neo4j cypher-shell -u neo4j -p password123 "RETURN 1"
```

## License

MIT License
