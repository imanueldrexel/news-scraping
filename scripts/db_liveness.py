#!/usr/bin/env python3
"""
OPS-36 (#209): is the production database answering, between the scheduled jobs?

On 2026-09-30 the Docker Desktop engine stalled for ~80 minutes: port 5431
still accepted TCP, every query hung, and nothing noticed, because nothing
touches the DB between the 05:00 backup, the 05:30 health check and the
07:00/19:00 crawls. This probe runs `SELECT 1` with a hard client-side deadline
(a stalled engine accepts the connection and never answers, so connect and
statement timeouts alone are not enough) and alerts through the Telegram
outbox on the transition:

  * DOWN after DB_LIVENESS_FAILS_BEFORE_ALERT failed probes in a row (default 2,
    so one blip is not an alert);
  * RECOVERED on the first good probe after a DOWN alert.

It never repeats an alert while the state holds, writes nothing to the DB,
and never raises. State lives in logs/db_liveness_state.json.

    venv\\Scripts\\python.exe scripts\\db_liveness.py          # exit 0 up, 1 down
    venv\\Scripts\\python.exe scripts\\db_liveness.py --check  # probe only, no state, no alert

Scheduled every 15 minutes by Task Scheduler (OPERATIONS.md, "DB liveness").
"""
import argparse
import json
import logging
import os
import sys
import threading
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(REPO_ROOT, ".env"))

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

STATE_PATH = os.getenv("DB_LIVENESS_STATE", os.path.join(REPO_ROOT, "logs", "db_liveness_state.json"))
DEADLINE_S = float(os.getenv("DB_LIVENESS_DEADLINE_S", 20))
FAILS_BEFORE_ALERT = int(os.getenv("DB_LIVENESS_FAILS_BEFORE_ALERT", 2))


def _select_one(result: dict) -> None:
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_DB_HOST", "localhost"), port=int(os.getenv("POSTGRES_DB_PORT", 5431)),
            user=os.getenv("POSTGRES_DB_USER", "postgres"), password=os.getenv("POSTGRES_DB_PASS", "postgres"),
            dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"),
            connect_timeout=int(DEADLINE_S), options="-c statement_timeout=%d" % int(DEADLINE_S * 1000))
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result["ok"] = cur.fetchone() == (1,)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 -- a probe reports, never raises
        result["error"] = f"{type(e).__name__}: {str(e).strip()[:200]}"


def probe(deadline_s: float = DEADLINE_S):
    """(ok, reason). The query runs in a daemon thread so a hung engine costs
    at most `deadline_s`; the thread is abandoned, not joined forever."""
    result = {}
    worker = threading.Thread(target=_select_one, args=(result,), daemon=True)
    worker.start()
    worker.join(deadline_s)
    if worker.is_alive():
        return False, f"no answer to SELECT 1 within {deadline_s:.0f}s (the engine accepts but does not respond)"
    if result.get("ok"):
        return True, None
    return False, result.get("error") or "SELECT 1 returned no row"


def load_state(path: str = None) -> dict:
    try:
        with open(path or STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"status": "up", "failures": 0, "since": None}


def save_state(state: dict, path: str = None) -> None:
    path = path or STATE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as e:
        logger.error(f"could not write {path}: {e}")


def step(state: dict, ok: bool, reason, now: str):
    """Pure: (new_state, alert_text or None). `status` is the last ALERTED
    state, so an alert goes out once per transition."""
    state = dict(state)
    if ok:
        alert = None
        if state.get("status") == "down":
            alert = (f"✅ NewsAggregator DB recovered at {now}: SELECT 1 answers again "
                     f"(down since {state.get('since')}).")
        return {"status": "up", "failures": 0, "since": None}, alert
    failures = int(state.get("failures") or 0) + 1
    since = state.get("since") or now
    if state.get("status") != "down" and failures >= FAILS_BEFORE_ALERT:
        return ({"status": "down", "failures": failures, "since": since},
                f"🛑 NewsAggregator DB DOWN since {since}: {failures} probes in a row failed. Last: {reason}. "
                f"Check `docker ps` / Docker Desktop (OPERATIONS.md, \"DB liveness\").")
    return {"status": state.get("status", "up"), "failures": failures, "since": since}, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="Probe and print only; no state, no alert")
    args = ap.parse_args(argv)
    ok, reason = probe()
    if args.check:
        print("up" if ok else f"DOWN: {reason}")
        return 0 if ok else 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    state, alert = step(load_state(), ok, reason, now)
    save_state(state)
    (logger.info if ok else logger.error)(f"db liveness: {'up' if ok else 'DOWN: ' + str(reason)}")
    if alert:
        try:
            from notify_telegram import send
            send(alert)
        except Exception as e:  # noqa: BLE001 -- never raise out of the probe
            logger.error(f"alert not sent ({type(e).__name__}: {e}): {alert}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
