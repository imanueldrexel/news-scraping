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


def main() -> int:
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
