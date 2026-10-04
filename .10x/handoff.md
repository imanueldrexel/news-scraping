# Current Handoff

## From: Product Manager -> To: SDE
**Date:** 2026-10-04
**Phase:** Requirements -> Implementation (SYS-39 #125)

### Context
Owner decision: knowledge extraction covers ALL news, on DeepSeek via SumoPod (pending the SYS-39 bake-off). Source of truth: `decisions/product-manager/knowledge-extraction-provider.md`; the requirement is also commented on #125.

### Requirements (priority order)
1. **P1 Measure first:** token counts from the provider response (input/output per article) into `api_usage_log`; replace the PM estimate (~1,050 tokens/article, ~4.3M tokens/day, ~$1.2/day off-peak) with real numbers.
2. **P1 Bake-off:** 200-article stratified fixture, DeepSeek vs the Gemini reference; entity agreement >= 0.85 (persons/orgs/locations), event_type agreement, parse-failure rate, 429 rate under load. Thinking disabled for the provider.
3. **P1 Implement behind `KnowledgeExtractor`** (strategy chosen by env var), keeping the OPS-09 transient-vs-deterministic error boundary and SYS-19 attempt tracking. `GEMINI_DAILY_CALL_LIMIT` (20) must stop gating DeepSeek calls; replace with a token/cost guard.
4. **P1 Peak-hours guard:** skip peak blocks (UTC weekdays 01:00-04:00 and 06:00-10:00) unless forced. Pricing: input $0.15/$0.30, output $0.60/$1.20 per 1M tokens (off-peak/peak); weekends all off-peak.
5. **P2 Catch-up ordering:** finance topics first, then everything else. Backlog is 84,606 articles (~$25 off-peak): run on a weekend after SumoPod rate limits are checked.

### Out of scope
Extraction schema, entity normaliser, newsletter, embeddings. Do not label #136 ready-for-qa until the owner confirms the provider choice on it.

### Open Questions
- SumoPod rate limits and what its daily-limit 429 body looks like (unverified, see SYS-71).
- Who reads the KB (`kb_query`, RAG)? Only affects reporting, not scope.

---

## Handoff History
- 2026-10-04 SDE -> QA (still pending QA): SYS-71 #219, SYS-72 #220, DBT-51 #221, DBT-52 #222 ready-for-qa, #216/#215/#204 re-labelled; #204 needs the 19:00 crawl; stray partial-day 2026-10-04 digest row awaits the owner. Full text: `decisions/sde/p1-p2-newsletter-fixes.md`, section "QA feedback fixed".
- 2026-10-04 QA -> SDE: fix SYS-71 first, then SYS-72, DBT-51, DBT-52; owner approved task=newsletter, SYS-67 as scoped, SYS-63 repair after SYS-72.

- 2026-10-04 planning -> SDE: P1/P2 fixes + newsletter (spec + ADR-001, ADR-002).
- 2026-10-04 brainstorming -> QA: verification of 9 ready-for-qa tickets (baseline done, see decisions/qa). QA pass is paused while dev work runs; scheduled-run evidence still pending.
- 2026-10-04 init-project -> first active role: state initialized.
