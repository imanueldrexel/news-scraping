# sys-63-sys-67-decisions — CTO

### 2026-10-04 — Owner decisions
**SYS-67 (#215): accept as scoped.** One scandal holds at most 2 slots per section (ADR-002). Two-way door: `NEWSLETTER_MAX_CLUSTERS_PER_STORY=0` turns it off. Unmet "<=1 contaminated cluster/day" moves to SYS-74 (#224, P3); four approaches already failed (EXPERIMENTS.md), so no new work without a new idea measured first. Review point: when OPS-38 schedules the newsletter.

**SYS-63 (#204) stored-row repair: yes, after SYS-72.** Owner uses RAG search and the entity KB, so dirty chunks matter. Tracked as SYS-73 (#223).
- Scope: ~34,720 of 84,606 articles (upper bound), 163,696 of 411,994 chunks (read-only count 2026-10-04).
- Order: SYS-72 (#220) -> dry run -> owner approval + fresh backup -> rewrite + re-embed under the run lock.
- Why not now: the cleaner still deletes real sentences; repairing first would make that loss permanent.
- One-way-ish door: reversible only through the DB backup and the FAISS pair.
