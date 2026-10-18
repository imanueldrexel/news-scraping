# staff-engineer decisions — index

## Active features
- [qa-1013-queue](qa-1013-queue.md) — 2026-10-19: QA 10-13 queue: SYS-144/145 own-subject rule + SYS-146 -nya roots (ADR-021), SYS-194 FTS order, DBT-60/70/71, SRC-62
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md)
- [rag-search-redesign](rag-search-redesign.md) — reuse newsletter_copy/story_summary/summarizer; copy-table and no-|safe rules; test map
- [chunks-fit-encoder-window](chunks-fit-encoder-window.md) — SYS-109: L2 chunks ≤ 80-word windows that fit MiniLM's 128 tokens (ADR-008); L2-only re-chunk; DBT-64 indexes
- [qa-senior-fixes-2026-10-12](qa-senior-fixes-2026-10-12.md) — 2026-10-12 QA + senior list: SYS-111/139/104/140/141/137/138/112/142, DBT-65/66/67; owner decisions; ADR-010/011/012
- [qa-second-pass-fixes-2026-10-12](qa-second-pass-fixes-2026-10-12.md) — QA second pass 2026-10-12: SYS-138 subject gate (ADR-013), SYS-143/144/145 (ADR-014), DBT-68/69, DBT-67 store_repair module (ADR-015)
- [newsletter-story-arcs](newsletter-story-arcs.md) — one home per concern (source_check, llm_json, newsletter_copy), pure moves proven byte-identical, side effects only in generate(), read-only NEWS_L1 (ADR-016/017)
