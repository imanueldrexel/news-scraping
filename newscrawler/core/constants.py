import os


S3_BUCKET = os.getenv("S3_BUCKET")
REGION = os.getenv("REGION", "ap-southeast-1")
VERBOSE = os.getenv("VERBOSE", "False") == "True"
# VERBOSE = False
# PARALLELIZE = os.getenv("PARALLELIZE", "False") == "True"
PARALLELIZE = True
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", 5))
SITEMAP_RECRAWL_COOLDOWN_DAYS = int(os.getenv("SITEMAP_RECRAWL_COOLDOWN_DAYS", 7))
# SYS-09: a sitemap whose URL fails to fetch/extract this many times in a row (not
# necessarily consecutive runs -- any run that doesn't produce a NewsDetailsDTO for
# it counts) is excluded from load_all_sitemaps, so a permanently-dead link stops
# consuming a retry slot forever. Still retried up to this many times first, since
# most failures are transient (a timeout, a momentary block).
SITEMAP_MAX_FETCH_FAILURES = int(os.getenv("SITEMAP_MAX_FETCH_FAILURES", 3))
# OPS-15: when at least this fraction of a run's attempted sitemaps for one source
# fail to fetch/extract, the failure is treated as the SOURCE's (a block, a TLS/DNS
# problem, a regression in the crawler) rather than 1,000 individually dead URLs:
# the run logs at ERROR and does not touch fetch_failures at all, so an outage
# cannot retire a source's whole queue. 1.0 = only when every single one failed.
SITEMAP_SOURCE_FAILURE_RATIO = float(os.getenv("SITEMAP_SOURCE_FAILURE_RATIO", 1.0))
# OPS-16 (#87): a ratio alone is undefined at small N. With 3 rows left in a
# source's eligible queue and all 3 dead, "100% failed" is not evidence the
# source is down -- it is evidence those 3 URLs are. Below this many failures the
# run is never called source-wide, so genuinely dead tails still retire under
# SYS-09's cap instead of being re-fetched on every run forever.
SITEMAP_SOURCE_FAILURE_MIN = int(os.getenv("SITEMAP_SOURCE_FAILURE_MIN", 20))
# SRC-55 (#201): this many HTTP 403/429 answers in a row from one source stop
# its full-text run (newscrawler/core/page_loader/throttle.py). The streak and
# the rows not yet fetched are left untouched -- no strike, no cooldown -- so a
# rate limit costs the rest of this run, not the URLs. KUMPARAN walls off after
# ~100-120 fetches; a single dead article answering 403 never makes a streak.
SOURCE_THROTTLE_STREAK = int(os.getenv("SOURCE_THROTTLE_STREAK", 10))
# Article text shorter than this (total chars) is treated as an extraction failure and
# handed to the next extractor (site selector -> trafilatura -> newspaper). 0 disables.
MIN_ARTICLE_CHARS = int(os.getenv("MIN_ARTICLE_CHARS", 200))
EXECUTABLE_PATH = os.getenv(
    "EXECUTABLE_PATH", "/Users/imanuel/Downloads/chromedriver_2"
)
MAX_WORKER = os.getenv("MAX_WORKER")
if MAX_WORKER:
    MAX_WORKER = int(MAX_WORKER)

# OPS-01: scripts/notify_telegram.py sends a message via the Bot API when the
# scheduled crawler health check finds a broken source. Both unset means
# notifications are silently skipped (logged, not raised) -- see that module.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TW_API_KEY = os.getenv("TW_API_KEY")
TW_API_SECRET_KEY = os.getenv("TW_API_SECRET_KEY")
TW_BEARER_TOKEN = os.getenv("TW_BEARER_TOKEN")


OPENAI_KEY = os.getenv("OPENAI_KEY")
OPEN_AI_MODEL = os.getenv("OPEN_AI_MODEL")

# VECTOR_DB_NAME = os.getenv("VECTOR_DB_NAME")
VECTOR_DB_NAME = os.getenv("VECTOR_DB_NAME", "NEWS_DEEPSEEK_8B")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-r1:8b")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "nomic-embed-text")

VECTOR_DB_NAME_L1 = os.getenv("VECTOR_DB_NAME_L1", "NEWS_L1")
VECTOR_DB_NAME_L2 = os.getenv("VECTOR_DB_NAME_L2", "NEWS_L2")
# DBT-13 (#48): consumed by HierarchicalChunker() as its defaults (validated
# there: 0 < min <= max, 0 <= overlap < max). Whitespace tokens, not model
# tokens. Changing them changes the L2 vector count (SYS-41).
CHUNK_MIN_TOKENS = int(os.getenv("CHUNK_MIN_TOKENS", 80))
CHUNK_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", 450))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", 50))
EMBEDDING_MODEL_HF = os.getenv("EMBEDDING_MODEL_HF", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# SYS-37 (#121): the INTERESTS phrase list that the cosine filter scored
# against is retired -- the news-worthy decision is the probe in
# newscrawler/core/models/ (trained by scripts/train_importance_probe.py on
# the SYS-36 gold set). SOFT_THRESHOLD overrides the artifact's CV-chosen
# P(soft) threshold (0.39 for the 2026-09-22 artifact); leave unset unless
# an audit (OPS-18) says the operating point must move.
_soft = os.getenv("SOFT_THRESHOLD")
SOFT_THRESHOLD = float(_soft) if _soft else None

# ── Knowledge Extraction (Phase 2) ──────────────────────────────────────────
GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL          = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DAILY_API_CALL_LIMIT  = int(os.getenv("DAILY_API_CALL_LIMIT", 1400))
# OPS-20 (#136): an OpenAI-compatible endpoint for the OFFLINE labeller
# (SYS-36) only -- owner decision 2026-09-20 after the Gemini free tier turned
# out to be 20 requests/day/model. Nothing in the per-article crawl path
# calls it. The openai SDK reads OPENAI_API_KEY/OPENAI_BASE_URL by name; the
# model is ours (SumoPod: "deepseek-v4-flash").
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL       = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL          = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
KNOWLEDGE_BATCH_SIZE  = int(os.getenv("KNOWLEDGE_BATCH_SIZE", 50))
# SYS-19: a poison article (unparseable Gemini response, or a response whose shape
# crashes _process_extraction) burns one Gemini call per run forever without this --
# it's re-selected as part of the newest-first pending query every single time.
KNOWLEDGE_EXTRACT_MAX_ATTEMPTS = int(os.getenv("KNOWLEDGE_EXTRACT_MAX_ATTEMPTS", 3))

# ── Newsletter (Phase 3) ─────────────────────────────────────────────────────
DBSCAN_EPS         = float(os.getenv("DBSCAN_EPS", 0.25))
DBSCAN_MIN_SAMPLES = int(os.getenv("DBSCAN_MIN_SAMPLES", 2))
DIGESTS_DIR        = os.getenv("DIGESTS_DIR", "digests")

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
}

NEWSLETTER_CATEGORY_KEYWORDS = {
    "macroeconomics": ["inflasi", "suku bunga", "bi rate", "gdp", "pdb", "apbn",
                       "neraca", "makroekonomi", "kebijakan moneter", "rupiah", "forex"],
    "capital_market": ["ihsg", "saham", "idx", "ipo", "rights issue", "emiten",
                       "bursa", "pasar modal", "obligasi", "sbr", "sukuk"],
    "banking":        ["bank", "ojk", "npl", "car", "kredit", "deposito",
                       "fintech", "perbankan", "lps", "pinjaman"],
    "corporate":      ["akuisisi", "merger", "direksi", "komisaris", "laba",
                       "rugi", "dividen", "korporasi", "anak perusahaan"],
    "commodities":    ["cpo", "sawit", "batu bara", "nikel", "minyak", "gas",
                       "lng", "komoditas", "tambang", "minerba"],
}

# ── RAG Search (Phase 4) ─────────────────────────────────────────────────────
RAG_SEMANTIC_WEIGHT = float(os.getenv("RAG_SEMANTIC_WEIGHT", 0.6))
RAG_BM25_WEIGHT     = float(os.getenv("RAG_BM25_WEIGHT", 0.3))
RAG_RECENCY_WEIGHT  = float(os.getenv("RAG_RECENCY_WEIGHT", 0.1))
RAG_TOP_K           = int(os.getenv("RAG_TOP_K", 5))
RAG_MIN_SEMANTIC_SCORE = float(os.getenv("RAG_MIN_SEMANTIC_SCORE", 0.60))