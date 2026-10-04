# knowledge-extraction-provider — PM

### 2026-10-04 — Should the Knowledge Extractor use DeepSeek (SumoPod)?
- **Recommendation:** Yes, as the intended provider, after SYS-39's bake-off passes; not before. Extract finance topics first.
- **Problem:** `knowledge_extracted = 0` for all 84,606 articles; `entities` = 54, `entity_mentions` = 32. The KB is effectively empty because the Gemini free tier allows 20 calls/day (OPS-20).
- **Token estimate (derived, not measured):** avg article body 2,390 chars after the 3,000-char cut (p50 2,644, p90 3,000; 3,000-row sample) ~ 650-700 tokens at ~3.5 chars/token, plus ~110 prompt tokens, ~760 in; JSON out ~300 (SYS-39's figure). ~1,050 tokens per article. Volume 2026-09-28..10-02: 20,351 saves = ~4,070/day. All topics: ~4.3M tokens/day (3.1M in, 1.2M out). Finance topics (markets, macro_policy, corporate, commodities_energy) = 6,748 = 33%: ~1,350 articles/day, ~1.4M tokens/day. Backlog of 84,606: ~89M tokens (64M in, 25M out), finance-only ~29M.
- **Success criteria (from SYS-39):** entity agreement >= 0.85 vs reference on a 200-article fixture; a real day extracted without hitting the cap; finance topics first on a catch-up run; cost per 1,000 articles recorded.
- **Unknown:** SumoPod price per token and its rate limits; tokens/article until measured (usage metadata); whether thinking must be disabled (it must, as for the summarizer, or output can balloon).
- **Open product question:** who reads the KB (`kb_query`, RAG)? Answer sets whether "all topics" or "finance first, rest later" is worth the spend.
