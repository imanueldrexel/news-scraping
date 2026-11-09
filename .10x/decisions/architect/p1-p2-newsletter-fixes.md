# p1-p2-newsletter-fixes — architect

### 2026-10-04 — Summarizer interface + degradation accounting
- **Decision:** ADR-001. `core/summarizer.py` (interface, OpenAI-compatible and Gemini implementations, `QuotaExhausted`); generator counts summarized vs fallback and stops after the first quota error.
- **Boundaries:** core (generator, summarizer) depends on no infrastructure; usage counting goes through the existing knowledge datasource counters injected by `DataFlowRepositoryImpl`.
- **Failure modes:** quota 429, endpoint outage, empty/garbled reply, reasoning model eating tokens; each degrades to the headline list and is counted.
- **Clustering/cleaner:** unchanged boundaries; cleaner lives in `core/utils/utils.py` and is called once from the base `Crawler`.
