#!/usr/bin/env python3
r"""
OPS-01: the scheduled entry point. Runs check_crawlers.py, and if it reports any
unhealthy source (exit code 1), sends a Telegram notification with the summary so
breakage is caught within a day instead of by a human noticing missing articles
weeks later.

Registered as a daily 05:30 WIB Windows Task Scheduler job (see OPERATIONS.md):
    schtasks /Create /TN "NewsAggregator Crawler Health Check" /SC DAILY /ST 05:30 ^
        /TR "<repo>\venv\Scripts\python.exe <repo>\scripts\run_scheduled_health_check.py" ^
        /RU "<user>"
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Set-ScheduledTask -TaskName "NewsAggregator Crawler Health Check" -Settings $s

-StartWhenAvailable runs the job late on next boot/logon if 05:30 was missed
(machine off or asleep) instead of skipping that day outright; -WakeToRun covers
the asleep case specifically. Without these two settings a missed window produces
no alert, no exit code, no crawl_log row and no JSON report -- indistinguishable
from a healthy run (OPS-01, #9, reopened 2026-09-17).

-AllowStartIfOnBatteries and -DontStopIfGoingOnBatteries override Task Scheduler's
defaults (DisallowStartIfOnBatteries=True, StopIfGoingOnBatteries=True), which
neither of the two settings above touch. This machine is a laptop -- without these,
the 05:30 trigger fires but the AC-power condition fails and the run is silently
skipped (not "missed", so -StartWhenAvailable never queues a catch-up run), or a
run in progress is killed mid-way if unplugged (OPS-01, #9, reopened a second time
2026-09-17).

Exits with check_crawlers.py's own exit code, so Task Scheduler's own history
("Last Run Result") also reflects success/failure independent of the notification.

OPS-13 (#76): check_crawlers.py is run with --json --log-db, and the message is
its `summary` -- which leads with what changed since each outlet's previous
crawl_log row (NEW / CHANGED / RECOVERED) rather than re-listing the same 17
known-broken outlets every morning. A notification is sent when the exit code is
non-zero (unchanged semantics) OR when the delta has any movement, so a recovery
on an otherwise all-green day is visible without opening crawl_log. Whether a
no-change day should notify at all is the operator's call, not the code's:
HEALTH_ALERT_ON_NO_CHANGE (default true) in .env.
"""
import json
import logging
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, REPO_ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except Exception:
    pass

# The summary now carries emoji; under Task Scheduler (and any cp1252 console) the
# default stderr encoding would make logging it a UnicodeEncodeError traceback.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# OPS-13: set HEALTH_ALERT_ON_NO_CHANGE=false in .env to stay silent on a day whose
# per-outlet statuses all match the previous run (the exit code still reflects the
# unhealthy outlets; only the Telegram send is skipped). Default on: a red run that
# says "no change" is still a red run until the operator decides otherwise.
HEALTH_ALERT_ON_NO_CHANGE = os.getenv("HEALTH_ALERT_ON_NO_CHANGE", "true").strip().lower() not in ("0", "false", "no")

# OPS-01 (#9): even with -StartWhenAvailable/-WakeToRun, the job can still stop
# firing entirely (task deleted, credentials expired, machine off longer than any
# catch-up window) -- and in that case nothing produces an alert, an exit code, or
# a crawl_log row, so nothing else would ever notice. A gap this large since the
# last logged run is itself the alert -- a channel-independent second signal that
# doesn't depend on *this* run having fired on schedule, only on it eventually
# firing at all.
MISSED_RUN_GAP_HOURS = 36

# OPS-18 (#123): the weekly filter-drift audit rides on this daily job, on this
# weekday (0 = Monday; -1 disables it). It alerts on its own; its failure never
# changes this job's exit code, which is about the crawlers.
FILTER_AUDIT_WEEKDAY = int(os.getenv("FILTER_AUDIT_WEEKDAY", 0))


def filter_audit_due(today) -> bool:
    return FILTER_AUDIT_WEEKDAY >= 0 and today.weekday() == FILTER_AUDIT_WEEKDAY


def run_filter_audit() -> int:
    result = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "audit_filter_drift.py")],
                            cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="replace")
    tail = " | ".join(((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-5:])
    log = logger.info if result.returncode == 0 else logger.error
    log(f"filter drift audit exit {result.returncode}: {tail}")
    return result.returncode


def _hours_since_last_health_check():
    """Hours since the most recent task='health_check' crawl_log row, or None if
    the query fails (DB unreachable) or no such row exists yet. Must be read
    before this run's own check_crawlers.py --log-db call writes new rows, so it
    reflects the gap since the *previous* run. Never raises -- a monitoring check
    must not be able to crash the health check it's attached to."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(REPO_ROOT, ".env"))
        from sqlalchemy import text
        from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
        client = SQLAlchemyClient()
        with client.get_session() as session:
            gap = session.execute(text(
                "SELECT EXTRACT(EPOCH FROM (NOW() - MAX(finished_at))) / 3600 "
                "FROM crawl_log WHERE task = 'health_check'"
            )).scalar()
        return float(gap) if gap is not None else None
    except Exception as e:
        logger.warning(f"Could not check for missed health-check runs: {e}")
        return None


def _stale_backup_message():
    """OPS-23 (#164): a message when the newest verified pg_dump is missing or older
    than DB_BACKUP_MAX_AGE_HOURS, else None. The backup job cannot report its own
    failure to fire, so this job does it. Never raises."""
    try:
        import backup_db
        age = backup_db.newest_dump_age_hours()
        limit = backup_db.MAX_AGE_HOURS
    except Exception as e:
        logger.warning(f"Could not check the database backup's age: {e}")
        return None
    if age is None:
        return "no verified dump in backups/pg_dump -- run scripts/backup_db.py"
    if age > limit:
        return (f"the newest dump is {age:.1f}h old (limit {limit:.0f}h) -- the backup job may not be "
                f'firing. Check `schtasks /Query /TN "NewsAggregator DB Backup" /FO LIST /V`.')
    return None


def main() -> int:
    gap_hours = _hours_since_last_health_check()
    if gap_hours is not None and gap_hours > MISSED_RUN_GAP_HOURS:
        from notify_telegram import send
        send(
            f"⏰ NewsAggregator health check gap: the last recorded run was "
            f"{gap_hours:.1f}h ago (expected ~daily) -- the scheduled job may not "
            f'be firing. Check `schtasks /Query /TN "NewsAggregator Crawler '
            f'Health Check" /FO LIST /V`.'
        )
        logger.warning(f"Missed-run gap detected: {gap_hours:.1f}h since last health_check row")

    stale_backup = _stale_backup_message()
    if stale_backup:
        from notify_telegram import send
        send(f"💾 NewsAggregator DB backup: {stale_backup}")
        logger.warning(stale_backup)

    python = sys.executable
    check_script = os.path.join(REPO_ROOT, "scripts", "check_crawlers.py")

    # --json rather than --quiet so the delta block is machine-readable here; the
    # summary text inside it is what --quiet would have printed. Decode as UTF-8
    # explicitly: the summary carries emoji and Windows' locale default (cp1252)
    # would mangle them or raise.
    result = subprocess.run(
        [python, check_script, "--json", "--log-db"],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "").strip()
    report = _parse_report(output)
    summary = report.get("summary") if report else output
    logger.info(summary or "(no output)")
    if result.stderr:
        logger.warning(result.stderr.strip())

    decision = decide_notification(result.returncode, report, HEALTH_ALERT_ON_NO_CHANGE)
    if decision["send"]:
        from notify_telegram import send
        body = summary or "check_crawlers.py reported unhealthy source(s) but produced no output."
        send(f"{decision['headline']}\n\n{body}")
    else:
        logger.info(f"No notification sent: {decision['reason']}")

    from datetime import date
    if filter_audit_due(date.today()):
        run_filter_audit()

    return result.returncode


def _parse_report(stdout: str):
    """The --json payload as a dict, or None if stdout isn't that (a crash trace,
    an empty run) -- in which case the raw text is what gets sent, as before."""
    try:
        report = json.loads(stdout)
        return report if isinstance(report, dict) else None
    except ValueError:
        return None


def decide_notification(returncode: int, report, alert_on_no_change: bool) -> dict:
    """Pure: whether to send, with which headline, and why not.

    Sends when the check exited non-zero (an UNHEALTHY outlet, unchanged OPS-01
    semantics) or when the OPS-13 delta shows movement -- so an all-green run that
    just recovered an outlet still tells the operator. Stays silent only on a
    no-change red day when the operator has set HEALTH_ALERT_ON_NO_CHANGE=false, or
    on an all-green, all-unchanged day (nothing to say)."""
    delta = (report or {}).get("delta") or {}
    moved = any(delta.get(k) for k in ("new", "changed", "recovered", "baseline"))
    no_change = bool(delta.get("no_change"))

    if returncode != 0:
        if no_change and not alert_on_no_change:
            return {"send": False, "headline": "",
                    "reason": "unhealthy outlets unchanged since the previous run and HEALTH_ALERT_ON_NO_CHANGE=false"}
        return {"send": True, "headline": "⚠️ NewsAggregator crawler health check found a problem:", "reason": ""}
    if moved:
        return {"send": True, "headline": "✅ NewsAggregator crawler health check: all sources healthy (with changes):", "reason": ""}
    return {"send": False, "headline": "", "reason": "all sources healthy, nothing changed"}


if __name__ == "__main__":
    sys.exit(main())
