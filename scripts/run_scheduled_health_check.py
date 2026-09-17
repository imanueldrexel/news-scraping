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
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Set-ScheduledTask -TaskName "NewsAggregator Crawler Health Check" -Settings $s

-StartWhenAvailable runs the job late on next boot/logon if 05:30 was missed
(machine off or asleep) instead of skipping that day outright; -WakeToRun covers
the asleep case specifically. Without these two settings a missed window produces
no alert, no exit code, no crawl_log row and no JSON report -- indistinguishable
from a healthy run (OPS-01, #9, reopened 2026-09-17).

Exits with check_crawlers.py's own exit code, so Task Scheduler's own history
("Last Run Result") also reflects success/failure independent of the notification.
"""
import logging
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, REPO_ROOT)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# OPS-01 (#9): even with -StartWhenAvailable/-WakeToRun, the job can still stop
# firing entirely (task deleted, credentials expired, machine off longer than any
# catch-up window) -- and in that case nothing produces an alert, an exit code, or
# a crawl_log row, so nothing else would ever notice. A gap this large since the
# last logged run is itself the alert -- a channel-independent second signal that
# doesn't depend on *this* run having fired on schedule, only on it eventually
# firing at all.
MISSED_RUN_GAP_HOURS = 36


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

    python = sys.executable
    check_script = os.path.join(REPO_ROOT, "scripts", "check_crawlers.py")

    result = subprocess.run(
        [python, check_script, "--quiet", "--log-db"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    logger.info(output or "(no output)")
    if result.stderr:
        logger.warning(result.stderr.strip())

    if result.returncode != 0:
        from notify_telegram import send
        summary = output or "check_crawlers.py reported unhealthy source(s) but produced no output."
        send(f"⚠️ NewsAggregator crawler health check found a problem:\n\n{summary}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
