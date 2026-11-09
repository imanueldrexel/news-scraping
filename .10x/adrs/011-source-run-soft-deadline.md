# ADR-011: A scheduled source run has a soft deadline before its hard kill; it stops starting batches, flushes its vectors and completes

**Status:** Accepted 2026-10-12 (owner chose "soft deadline only", no periodic flush)
**Date:** 2026-10-12
**Feature:** qa-senior-fixes-2026-10-12 (SYS-139 #320)
**Amends:** OPS-22's worker contract (`newscrawler/tools/source_worker.py`): "a timeout is a kill" still holds as the backstop.

## Context
- VIVA's full_text was killed at its 1,200 s timeout twice in a row, both times inside batch 10 of 10.
- A source's vectors are flushed once, at the end of its run (DBT-10: one ~1.6 GB index rewrite per source, ~18 s for VIVA). A kill therefore drops the whole run's FAISS work, 400+ articles, and also the SYS-57 sweep.
- Articles and chunk rows are committed per batch, so they survive without vectors, and the heal adds that work to the next run.
- Batches took 1.2-2.7 min.

## Decision
1. The parent sends the source's timeout with the job: `(website, task, timeout_s)`. The child sets `deadline = monotonic() + timeout_s - SCHEDULE_SOFT_DEADLINE_MARGIN_S` (default 180 s). The margin covers the end-of-run steps: SYS-09 failure recording, the SYS-54 discard, filter stats and the flush.
2. `CrawlerAPI.crawl_website(website, task, deadline=None)` passes the deadline to `crawl_newsdetails`. Every other caller (lambda handler, scripts) passes none, and nothing changes for them.
3. Before each batch after the first, the run stops when `now + longest batch so far > deadline`. Stopping means:
   - the rows not offered are left untouched (no strike, no cooldown, not in OPS-16's denominator), and the next run continues the queue;
   - the end-of-run steps and the flush run as normal;
   - `crawl_log` is `completed`, with the note `stopped early (SYS-139): N of M batches before the soft deadline; K rows left for the next run`.
4. The hard kill stays. A single batch longer than the margin is still killed, as today.

## Alternatives Considered
| Alternative | Pros | Cons | Why not |
|---|---|---|---|
| Flush every N batches | A crash loses at most N batches too | Each flush rewrites ~1.6 GB (DBT-10 removed per-batch saves for that) | Owner: soft deadline only |
| Only raise VIVA's timeout | No code | Grows with the backlog; any slow day kills again | Kept as quick relief; the VIVA entry is removed when this lands |

## Consequences
- **Positive:** a slow source saves everything it fetched, and "stopped early" is visible in `crawl_log` instead of a kill.
- **Negative:** a slow run does fewer rows (the queue drains over more runs), and one more knob.
- **Risk:** a first batch longer than `timeout - margin` is still killed. The note's batch count makes that visible.
