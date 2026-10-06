# RAG search redesign: operability (2026-10-07)

## Signals
- **Start-up:** `RAG warm-up done in Ns` (~15 s), or `RAG warm-up failed …` (ERROR). On a failure the first question loads the model instead.
- **Per question:** `rag retrieve ms=… semantic=… fts=… kept=… filters=…` and `rag answer status=… ms=… tokens=…/… cost=$…`.
- **Spend:** `SELECT * FROM api_usage_log WHERE api_name LIKE 'web:%' ORDER BY log_date DESC;`.
- **Health:** `/api/health` (unchanged) shows the FAISS indexes in memory against those on disk.

## Expected values (2026-10-07)
- Retrieval: 60-130 ms.
- Answer: 1.4-5 s.
- Cost: ~$0.0003-0.0004 per answer on DeepSeek.

## Failure runbook
OPERATIONS.md, "Search page: Ringkasan AI sedang tidak tersedia" and "a filter returns nothing".
- The page degrades to articles only. There is no alert: it is a local, owner-facing tool. Add one if the page becomes shared.
- The daily cap resets at 07:00 WIB (UTC date).

## SLO
None set. It is a local tool; revisit if it is shared.
