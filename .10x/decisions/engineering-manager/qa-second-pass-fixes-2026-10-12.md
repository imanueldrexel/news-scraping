# EM: dev fixes of QA's second pass (2026-10-12)

Order (each item = code + tests + mutants + ticket evidence, then `status: ready-for-qa`):
1. SYS-144 adverbs (small; SYS-145 depends on it).
2. SYS-143 refusal/list check + DBT-69's unusable-reply test.
3. SYS-145 kept-thread (ADR-014).
4. SYS-138 subject gate (ADR-013) + missing tests (picked dates, below-floor week hits) + live probe.
5. DBT-69 integration tests (drop script `--source`, 80/81-word boundary) on the test DB.
6. DBT-68 duplicate class + AST hygiene test.
7. DBT-67 refactor, its own commit, after 1-6 are green.
8. Live measurement (read-only): week probe, replay, follow-up probes (`--fallback` free; the LLM path only if the key works).
9. EXPERIMENTS.md, state files, ticket comments, commit.

Risks:
- The SumoPod key may be blocked or the balance low: then measure the fallback only, and say so on the ticket.
- DBT-67 is wide: do it last so it can be dropped without blocking the bug fixes.
