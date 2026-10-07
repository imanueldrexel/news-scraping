import os


S3_BUCKET = os.getenv("S3_BUCKET")
REGION = os.getenv("REGION", "ap-southeast-1")
VERBOSE = os.getenv("VERBOSE", "False") == "True"
# VERBOSE = False
# PARALLELIZE = os.getenv("PARALLELIZE", "False") == "True"
PARALLELIZE = True
# SYS-66 (#213): retries of a connection error / read timeout, with exponential
# backoff and jitter between them (base * 2**n, capped). Five immediate retries
# used to fail in milliseconds ("after 5 retries" in 0.1 s), so a sub-second
# blip parked good articles for the 7-day cooldown.
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", 3))
REQUEST_RETRY_BACKOFF_S = float(os.getenv("REQUEST_RETRY_BACKOFF_S", 1.0))
REQUEST_RETRY_BACKOFF_MAX_S = float(os.getenv("REQUEST_RETRY_BACKOFF_MAX_S", 8.0))
# SYS-70 (#218): a 429/503 with a Retry-After at most this long is waited out
# once (the whole host pauses, not just the one request).
REQUEST_RETRY_AFTER_MAX_S = float(os.getenv("REQUEST_RETRY_AFTER_MAX_S", 60.0))
# SYS-70: the crawler says what it is. CRAWLER_CONTACT (a URL or mailto:) is
# appended as "(+contact)" when set. Owner decision 2026-10-03: no contact yet.
CRAWLER_USER_AGENT = os.getenv("CRAWLER_USER_AGENT", "NewsAggregatorBot/1.0")
CRAWLER_CONTACT = os.getenv("CRAWLER_CONTACT", "").strip()
# SYS-70: hosts (suffix match) that answer 403 to the bot UA and are served the
# browser UA instead. Measured 2026-10-03 (scripts/experiments/probe_bot_ua.py):
# BERITASATU and INVESTORID refuse it on index and articles, TRIBUN on articles;
# the other 23 working sources serve it. Owner decision 2026-10-03.
BROWSER_UA_HOSTS = os.getenv("BROWSER_UA_HOSTS", "beritasatu.com,investor.id,tribunnews.com")
# SYS-70: per-host politeness, "host=value,..." (suffix match: kumparan.com
# covers m.kumparan.com). Minimum seconds between request starts to one host,
# and the most requests in flight to it at once. Owner decision 2026-10-03:
# keep throughput, pace only where measured. KUMPARAN walls off after ~110-130
# fast requests and served 250 paced at ~1 req/s without one 403 (SRC-55 probe).
HOST_MIN_INTERVAL_S = os.getenv("HOST_MIN_INTERVAL_S", "kumparan.com=1.0")
HOST_MAX_CONCURRENCY = os.getenv("HOST_MAX_CONCURRENCY", "")
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
# OPS-20 (#136): two budgets, because the two providers have two quotas.
# GEMINI_DAILY_CALL_LIMIT is Gemini's per-model requests/day: this project's
# free tier enforces 20 (429 ...GenerateRequestsPerDayPerProjectPerModel-FreeTier,
# 2026-09-20), so the default is 20 and the extractor stops there cleanly instead
# of spinning on 429s; raise it only after enabling billing. DAILY_API_CALL_LIMIT
# is the budget of the OpenAI-compatible endpoint (labeller, newsletter).
GEMINI_DAILY_CALL_LIMIT = int(os.getenv("GEMINI_DAILY_CALL_LIMIT", 20))
DAILY_API_CALL_LIMIT  = int(os.getenv("DAILY_API_CALL_LIMIT", 1400))
# OPS-20 (#136): an OpenAI-compatible endpoint -- owner decision 2026-09-20 for
# the offline labeller (SYS-36) after the Gemini free tier turned out to be 20
# requests/day/model, and 2026-10-04 for the newsletter's summaries (SYS-68).
# Knowledge extraction (SYS-39) uses it only when KNOWLEDGE_LLM_PROVIDER=openai. The openai SDK
# reads OPENAI_API_KEY/OPENAI_BASE_URL by name; the model is ours (SumoPod:
# "deepseek-v4-flash").
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL       = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL          = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
# SYS-39 (#125, ADR-003): knowledge extraction's provider is configuration:
# "openai" (the OpenAI-compatible endpoint above -- SumoPod's DeepSeek) or "gemini".
# Empty means gemini, today's behaviour: the switch spends money, so it is made on
# purpose, after the SYS-39 bake-off and the owner's confirmation on #136.
KNOWLEDGE_LLM_PROVIDER = os.getenv("KNOWLEDGE_LLM_PROVIDER", "").strip().lower()
KNOWLEDGE_REQUEST_TIMEOUT_S = float(os.getenv("KNOWLEDGE_REQUEST_TIMEOUT_S", 60))
# The reply cap. The bake-off's average reply is ~310 tokens but a long article lists dozens of
# entities; at 1,200 one in ~100 was cut mid-JSON (SYS-78). Only tokens used are billed.
KNOWLEDGE_MAX_OUTPUT_TOKENS = int(os.getenv("KNOWLEDGE_MAX_OUTPUT_TOKENS", 3000))
# KNOWLEDGE_BATCH_SIZE is how many pending articles one query fetches; a run keeps
# fetching until the queue is empty, KNOWLEDGE_MAX_PER_RUN articles were tried, or
# a stop condition below fires. (It used to be the whole run: 50.)
KNOWLEDGE_BATCH_SIZE  = int(os.getenv("KNOWLEDGE_BATCH_SIZE", 50))
KNOWLEDGE_MAX_PER_RUN = int(os.getenv("KNOWLEDGE_MAX_PER_RUN", 6000))
# Provider calls in flight at once (SYS-39, ADR-004). 1 is serial. The 2026-10-04 bake-off ran 4 with
# no 429 and no parse failure; calls take ~3 s, so 4 workers turn ~3.5 h per 4,000 articles into ~55 min.
KNOWLEDGE_WORKERS = int(os.getenv("KNOWLEDGE_WORKERS", 4))
# Stop conditions of a run on a priced provider. The budget is dollars per day
# (the day's api_usage_log.cost_usd), not requests: a normal day is ~$1.2
# off-peak, so 5 is a guard against a runaway, not a target; the 84,606-article
# backlog (~$25 off-peak) needs it raised for that one run.
KNOWLEDGE_DAILY_COST_LIMIT_USD = float(os.getenv("KNOWLEDGE_DAILY_COST_LIMIT_USD", 5.0))
# After this many failed calls in a row the provider is down; stop instead of
# trying every remaining article.
KNOWLEDGE_MAX_CONSECUTIVE_ERRORS = int(os.getenv("KNOWLEDGE_MAX_CONSECUTIVE_ERRORS", 5))
# The provider charges double in its peak window (core/peak_hours.py); a run does
# not start or continue inside it unless this is true.
KNOWLEDGE_ALLOW_PEAK = os.getenv("KNOWLEDGE_ALLOW_PEAK", "").strip().lower() in ("1", "true", "yes")
# USD per 1M tokens (owner, 2026-10-04: SumoPod DeepSeek).
KNOWLEDGE_PRICE_INPUT_OFFPEAK  = float(os.getenv("KNOWLEDGE_PRICE_INPUT_OFFPEAK", 0.15))
KNOWLEDGE_PRICE_INPUT_PEAK     = float(os.getenv("KNOWLEDGE_PRICE_INPUT_PEAK", 0.30))
KNOWLEDGE_PRICE_OUTPUT_OFFPEAK = float(os.getenv("KNOWLEDGE_PRICE_OUTPUT_OFFPEAK", 0.60))
KNOWLEDGE_PRICE_OUTPUT_PEAK    = float(os.getenv("KNOWLEDGE_PRICE_OUTPUT_PEAK", 1.20))
# SYS-19: a poison article (unparseable Gemini response, or a response whose shape
# crashes _process_extraction) burns one Gemini call per run forever without this --
# it's re-selected as part of the newest-first pending query every single time.
KNOWLEDGE_EXTRACT_MAX_ATTEMPTS = int(os.getenv("KNOWLEDGE_EXTRACT_MAX_ATTEMPTS", 3))

# ── Newsletter (Phase 3) ─────────────────────────────────────────────────────
# SYS-40 (#126): the digest groups each topic's articles with average-linkage
# agglomerative clustering (cosine). DBSCAN at eps 0.25 chained a busy topic
# into one cluster (2026-09-28: 221 of 372 markets articles, 245 of 838
# law_crime); average linkage does not chain. Measured in EXPERIMENTS.md
# "SYS-40: DBSCAN chains a busy topic".
NEWSLETTER_CLUSTER_DISTANCE = float(os.getenv("NEWSLETTER_CLUSTER_DISTANCE", 0.30))
NEWSLETTER_MIN_CLUSTER_SIZE = int(os.getenv("NEWSLETTER_MIN_CLUSTER_SIZE", 2))
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
    "ANTARANEWS":   0.70,     # SYS-85: the stored source name ("ANTARA" never matched)
}

# SYS-40 (#126): the digest shows at most this many clusters per topic
# section (ranked by size x distinct sources); the rest is one "and N more" line.
NEWSLETTER_MAX_CLUSTERS_PER_TOPIC = int(os.getenv("NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", 8))

# SYS-68 (#216) / ADR-001: who writes the cluster summaries and what happens
# when they cannot. "" prefers the OpenAI-compatible endpoint when its key is
# set, then Gemini; "openai" / "gemini" force one. A digest whose share of real
# summaries is under NEWSLETTER_MIN_SUMMARY_SHARE is logged at ERROR and noted
# on its crawl_log row; N consecutive failed calls stop the calls (an outage).
NEWSLETTER_LLM_PROVIDER = os.getenv("NEWSLETTER_LLM_PROVIDER", "").strip().lower()
NEWSLETTER_MIN_SUMMARY_SHARE = float(os.getenv("NEWSLETTER_MIN_SUMMARY_SHARE", 0.8))
NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS = int(os.getenv("NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 5))
NEWSLETTER_SUMMARY_TIMEOUT_S = float(os.getenv("NEWSLETTER_SUMMARY_TIMEOUT_S", 60))
NEWSLETTER_SUMMARY_MAX_TOKENS = int(os.getenv("NEWSLETTER_SUMMARY_MAX_TOKENS", 600))

# SYS-67 (#215): one scandal covered from many angles used to fill five of a section's eight
# slots. The summarizer is asked once per section which of its best 2x NEWSLETTER_MAX_CLUSTERS_PER_TOPIC
# clusters tell one story (core/story_grouping.py), and a section shows at most this many
# clusters of one story; the rest join its "and N more" line. 0 turns the grouping off.
NEWSLETTER_MAX_CLUSTERS_PER_STORY = int(os.getenv("NEWSLETTER_MAX_CLUSTERS_PER_STORY", 2))

# ── RAG Search (Phase 4) ─────────────────────────────────────────────────────
RAG_SEMANTIC_WEIGHT = float(os.getenv("RAG_SEMANTIC_WEIGHT", 0.6))
RAG_BM25_WEIGHT     = float(os.getenv("RAG_BM25_WEIGHT", 0.3))    # the keyword half (ADR-006: a coverage, not BM25)
RAG_RECENCY_WEIGHT  = float(os.getenv("RAG_RECENCY_WEIGHT", 0.1))
RAG_TOP_K           = int(os.getenv("RAG_TOP_K", 5))
RAG_MIN_SEMANTIC_SCORE = float(os.getenv("RAG_MIN_SEMANTIC_SCORE", 0.60))
# SYS-103 (#273, ADR-006): a keyword hit below the semantic floor is kept when it covers at
# least this share of the question's IDF-weighted words (0..1).
RAG_MIN_KEYWORD_COVERAGE = float(os.getenv("RAG_MIN_KEYWORD_COVERAGE", 0.6))
# SYS-98 (#267, ADR-005): who writes the search page's answers. "openai" (the owner's
# choice 2026-10-07: SumoPod's DeepSeek) or "gemini" (20 requests/day on the free tier).
# A forced provider without its key means no answers (the page shows articles only),
# never the other provider. Empty prefers the OpenAI-compatible endpoint, like the newsletter.
RAG_LLM_PROVIDER = os.getenv("RAG_LLM_PROVIDER", "openai").strip().lower()
# The page's own spend cap per day, in dollars of api_usage_log under `web:<model>`
# (never the extraction's key). ~$0.001 per answer, so $1 is ~1,000 answers.
RAG_DAILY_COST_LIMIT_USD = float(os.getenv("RAG_DAILY_COST_LIMIT_USD", 1.0))
RAG_ANSWER_TIMEOUT_S = float(os.getenv("RAG_ANSWER_TIMEOUT_S", 30))
RAG_ANSWER_MAX_TOKENS = int(os.getenv("RAG_ANSWER_MAX_TOKENS", 600))
# SYS-92/SYS-100: with a topic / portal / date filter the FAISS search over-fetches this
# many paragraphs before filtering on the database's metadata (a flat index costs the same).
RAG_FILTERED_K = int(os.getenv("RAG_FILTERED_K", 200))
RAG_QUESTION_MAX_CHARS = int(os.getenv("RAG_QUESTION_MAX_CHARS", 500))
# SYS-102: load the embedding model and FAISS when the web app starts, so the first
# question is not the slow one. 0 turns it off (the first request then loads them).
RAG_WARM_AT_STARTUP = os.getenv("RAG_WARM_AT_STARTUP", "1").strip() not in ("0", "false", "no", "")