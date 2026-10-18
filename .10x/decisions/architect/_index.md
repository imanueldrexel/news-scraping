# architect decisions — index

## Active features
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md)
- [rag-search-redesign](rag-search-redesign.md) — tracker #272: components, data flow, boundaries, failure modes (ADR-005)
- [rag-keyword-search](rag-keyword-search.md) — SYS-103: keyword half by rare-word anchors + IDF-weighted coverage, df from pg_stats (ADR-006)
- [chunks-fit-encoder-window](chunks-fit-encoder-window.md) — SYS-109: L2 chunks ≤ 80-word windows that fit MiniLM's 128 tokens (ADR-008); L2-only re-chunk; DBT-64 indexes
- [qa-senior-fixes-2026-10-12](qa-senior-fixes-2026-10-12.md) — 2026-10-12 QA + senior list: SYS-111/139/104/140/141/137/138/112/142, DBT-65/66/67; owner decisions; ADR-010/011/012
- [qa-second-pass-fixes-2026-10-12](qa-second-pass-fixes-2026-10-12.md) — QA second pass 2026-10-12: SYS-138 subject gate (ADR-013), SYS-143/144/145 (ADR-014), DBT-68/69, DBT-67 store_repair module (ADR-015)
- [open-p2-p3-2026-10-12](open-p2-p3-2026-10-12.md) — SRC-59 INVESTORID via sitemap_post.xml, DBT-60 date rule, SYS-91 FAISS posted_at repair
- [newsletter-story-arcs](newsletter-story-arcs.md) — top 3-4 stories as pure-prose arcs: in-edition stage, NEWS_L1 thread finder, model-confirmed `alur` + code guards, `NEWSLETTER_ARCS` switch, no thread store (ADR-016); core seams first: source_check, ask_json, plan/build, own composition root (ADR-017); tracker #336
- ADR-018 (2026-10-17): story-arc causal claims anchored to one quoted source sentence, checked by code; judge shadow-only (SYS-152, SYS-180)
- ADR-019 (2026-10-17): the causal gate matches a claim to ONE link of the quote by direction (cause to cause side, effect to effect side), with sides cut from the source sentences the quote covers; amends ADR-018 decision 2 (SYS-152/181..185)
- ADR-020 (2026-10-18): a causal half is covered whole (owner: every word), names never cross the link, the previous sentence is lent only to a reference, unlisted causal verbs gated (purpose exemption), polarity and hedges carry over, lists checked per item (SYS-188/181/189/185/192/183/187)
