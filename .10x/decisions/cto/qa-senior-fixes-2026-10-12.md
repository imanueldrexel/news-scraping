# CTO: QA + senior ticket list, 2026-10-12

Owner decisions (asked by dev as CTO/PM, 2026-10-12):
- **SYS-139:** soft deadline only (ADR-011). No periodic flush: each flush is a ~1.6 GB index rewrite.
- **SYS-104/140:** spend one LLM call per follow-up to rewrite it into a standalone question (ADR-010). This reverses ADR-007's "no model call" for follow-ups. Cost < $0.0001 per follow-up, counted in the page's own daily cap.
- **SYS-137:** production write approved: delete the queued sitemaps' stale chunk rows and vectors, and re-chunk the articles that adopted stale chunks. Backup first, run lock, between crawls.
- **SYS-138/112:** soft date window for "this week"; freshness only for articles about the question (ADR-012).
