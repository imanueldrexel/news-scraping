import os


S3_BUCKET = os.getenv("S3_BUCKET")
REGION = os.getenv("REGION", "ap-southeast-1")
VERBOSE = os.getenv("VERBOSE", "False") == "True"
# VERBOSE = False
# PARALLELIZE = os.getenv("PARALLELIZE", "False") == "True"
PARALLELIZE = True
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", 5))
SITEMAP_RECRAWL_COOLDOWN_DAYS = int(os.getenv("SITEMAP_RECRAWL_COOLDOWN_DAYS", 7))
EXECUTABLE_PATH = os.getenv(
    "EXECUTABLE_PATH", "/Users/imanuel/Downloads/chromedriver_2"
)
MAX_WORKER = os.getenv("MAX_WORKER")
if MAX_WORKER:
    MAX_WORKER = int(MAX_WORKER)
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
CHUNK_MIN_TOKENS = int(os.getenv("CHUNK_MIN_TOKENS", 80))
CHUNK_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", 450))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", 50))
EMBEDDING_MODEL_HF = os.getenv("EMBEDDING_MODEL_HF", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
INTERESTS = [
    "Pasar Saham", "Keuangan", "Ekonomi", "Makroekonomi", "Mikroekonomi",
    "Inflasi", "Suku Bunga", "Kebijakan Bank Sentral", "Pertumbuhan PDB",
    "Laporan Keuangan Perusahaan", "Berita Penggerak Pasar", "Investasi",
    "Komoditas", "Forex", "IHSG", "Rupiah"
]

# ── Knowledge Extraction (Phase 2) ──────────────────────────────────────────
GEMINI_API_KEY        = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL          = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DAILY_API_CALL_LIMIT  = int(os.getenv("DAILY_API_CALL_LIMIT", 1400))
KNOWLEDGE_BATCH_SIZE  = int(os.getenv("KNOWLEDGE_BATCH_SIZE", 50))

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