# EM: QA + senior ticket list, 2026-10-12

Order (each one commits separately with `Refs #N` and is labelled `status: ready-for-qa` with evidence):
1. SYS-111: small, P1, first.
2. SYS-139: before the next crawl if possible. The `.env` relief stays until QA sees 3 completed runs.
3. SYS-104 + SYS-140: the largest; measure on production (read-only) before and after.
4. SYS-141, DBT-66, DBT-65: small.
5. SYS-137: code + check now; the production write in the night window after the 19:00 crawl.
6. SYS-138 + SYS-112: measurement-driven.
7. SYS-142: measurement only.
8. DBT-67: blocked on QA closing SYS-111.

Risks:
- The SumoPod balance is needed to measure ADR-010 live (topped up 10-12).
- The production write must not overlap the 19:00 / 07:00 crawls (run lock) or the 21:00 extraction.
