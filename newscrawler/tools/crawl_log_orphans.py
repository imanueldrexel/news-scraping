"""OPS-39 (#232): crawl_log rows that no run will ever close.

A run writes its crawl_log row as 'started' and closes it when it ends. A run that
was killed or crashed before OPS-11/OPS-22 closed its rows left them 'started'
forever (five, 16-130 days old, on 2026-10-06), and `status = 'started'` is the
runbook's "is a run going?" question -- it answered "five sources are running" at
every hour of every day.

A row is an orphan once it is older than its job's Task Scheduler
`ExecutionTimeLimit`: by then Task Scheduler has ended the process that wrote it.
The limits are per task, because the knowledge extraction may legitimately run for
8 h; every other scheduled job (crawl 4 h, health check 2 h, newsletter 1 h) is
covered by the crawl's 4 h. Read by the 05:30 health check (which reports them) and
by scripts/close_abandoned_crawl_log.py (which closes them).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence

from sqlalchemy import text

ORPHAN_AFTER_HOURS = {"extract_knowledge": 8.0}    # "NewsAggregator Knowledge Extraction": PT8H
DEFAULT_ORPHAN_AFTER_HOURS = 4.0                    # "NewsAggregator Scheduled Crawl": PT4H, the longest of the rest


@dataclass(frozen=True)
class OpenRow:
    log_id: int
    website: str
    task: str
    started_at: datetime
    age_hours: float


def limit_hours(task: str) -> float:
    return ORPHAN_AFTER_HOURS.get(task, DEFAULT_ORPHAN_AFTER_HOURS)


def is_orphan(task: str, age_hours: float) -> bool:
    """True when a row of `task` started `age_hours` ago can no longer belong to a live run."""
    return age_hours > limit_hours(task)


def find_orphans(session) -> List[OpenRow]:
    """Every 'started' row past its job's limit, oldest first. Ages are the database's
    NOW() minus started_at, so the machine's clock and time zone do not enter."""
    rows = session.execute(text(
        "SELECT log_id, website, task, started_at, EXTRACT(EPOCH FROM (NOW() - started_at)) / 3600 AS age "
        "FROM crawl_log WHERE status = 'started' ORDER BY started_at"
    )).fetchall()
    return [OpenRow(r.log_id, r.website, r.task, r.started_at, float(r.age)) for r in rows
            if is_orphan(r.task, float(r.age))]


def close_orphans(session, rows: Sequence[OpenRow], reason: str) -> int:
    """Close `rows` as failed, `finished_at = started_at` (when the run really ended is
    not known), `error_msg = reason`. Only rows still 'started' are touched. Commits;
    returns how many were closed."""
    if not rows:
        return 0
    result = session.execute(text(
        "UPDATE crawl_log SET status = 'failed', finished_at = started_at, error_msg = :reason "
        "WHERE log_id = ANY(:ids) AND status = 'started'"
    ), {"reason": reason[:1000], "ids": [r.log_id for r in rows]})
    session.commit()
    return result.rowcount


def describe(rows: Sequence[OpenRow], limit: int = 5) -> str:
    """'#2 WARTAEKONOMI full_text since 2026-05-29 23:36 (3,118 h); ...' for a message."""
    head = "; ".join(f"#{r.log_id} {r.website} {r.task} since {r.started_at:%Y-%m-%d %H:%M} ({r.age_hours:,.0f} h)"
                     for r in rows[:limit])
    return head + (f"; +{len(rows) - limit} more" if len(rows) > limit else "")
