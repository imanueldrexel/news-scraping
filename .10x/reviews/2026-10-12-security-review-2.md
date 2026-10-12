# Security review 2026-10-12 (second pass): the dev's fixes of the 2026-10-12 list

| Area | Finding |
|---|---|
| Follow-up rewrite (ADR-010) prompt injection | The reader's text goes into a prompt as quoted data. The model's output is used only as a search string: SQL bind parameters (`_word_tests`, `lexeme` strips quotes and backslashes), the embedding, and the log line (truncated to 200 chars). It is never rendered or executed. A malicious follow-up can at worst choose its own cards, which the reader can do anyway. Accepted. |
| Rewrite output that is a refusal | Not a security issue: a quality defect (SYS-143). |
| Cost / abuse | The rewrite is capped by `RAG_DAILY_COST_LIMIT_USD`, with one attempt and no retry or wait. A paid reply that fails the check is counted, but no test guards that (DBT-69). |
| `.env` / secrets | No new secret. `SCHEDULE_SOFT_DEADLINE_MARGIN_S` is a plain integer. The QA probes use an in-memory ledger and write nothing. |
| Store-repair scripts (SYS-137) | Run lock + backup + dry-run default. The `--source` scope is untested (DBT-69): a scope guard on a destructive script. |
| Postgres `shm_size` (OPS-49) | No exposure change: same ports, same volume. |

No security blocker.
