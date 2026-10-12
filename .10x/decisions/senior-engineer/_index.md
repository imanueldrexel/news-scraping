# senior-engineer decisions — index

## Active features
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md)
- [rag-search-redesign](rag-search-redesign.md) — citation parsing, number-check corpus, OOB session id, two-step answer, warm-up
- [chunks-fit-encoder-window](chunks-fit-encoder-window.md) — SYS-109: L2 chunks ≤ 80-word windows that fit MiniLM's 128 tokens (ADR-008); L2-only re-chunk; DBT-64 indexes
- [code-quality-audit-2026-10-12](code-quality-audit-2026-10-12.md) — audit of c69d34d..f7f8672: SYS-140 (P2), SYS-141, SYS-142, DBT-67 filed

## Cross-cutting principles
- A comment states the invariant plus a ticket pointer; the before/after story goes in the commit and EXPERIMENTS.md (a docstring left describing a fixed bug is SYS-141).
- When a change feeds new input into an existing function (joined thread → `terms`), add one test of the composed path; mutation testing does not find untested seams.
- A reader that can see a swapped attribute (`vs_l2` under `refresh_stale`) captures it once per call.
- Scripts never import scripts: shared repair steps live in `newscrawler/tools/` (DBT-67).
- [qa-senior-fixes-2026-10-12](qa-senior-fixes-2026-10-12.md) — 2026-10-12 QA + senior list: SYS-111/139/104/140/141/137/138/112/142, DBT-65/66/67; owner decisions; ADR-010/011/012
