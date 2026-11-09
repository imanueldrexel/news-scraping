#!/usr/bin/env python3
r"""
OPS-23 (#164): dated pg_dump of the production database, with retention.

Until 2026-09-25 there was no dump of `newsaggregator` anywhere -- `backups/` holds
only per-migration JSON snapshots -- while the data sat in an anonymous Docker
volume one `docker volume prune` away from gone.

    venv\Scripts\python.exe scripts\backup_db.py            # dump, verify, prune
    venv\Scripts\python.exe scripts\backup_db.py --keep 30
    venv\Scripts\python.exe scripts\backup_db.py --check    # age of the newest dump only

What a run does, in order:
1. Finds the Postgres container: DB_CONTAINER if set, else the one running
   container that publishes POSTGRES_DB_PORT. pg_dump runs *inside* it, so the
   client always matches the server version and the host needs no Postgres install.
2. Streams `pg_dump -Fc` to `backups/pg_dump/<db>_<UTC stamp>.dump.partial`.
3. Verifies it: pipes the file back through `pg_restore --list` and requires a
   TABLE DATA entry for every table in REQUIRED_TABLES. A truncated or empty dump
   fails here, not on the day it is needed.
4. Renames it to `.dump`, then deletes all but the newest --keep dumps. Retention
   runs only after a verified dump exists, so a failing backup never deletes the
   last good one.
5. On any failure: Telegram (OPS-01 notifier) and exit 1.

Registered as a daily Task Scheduler job (OPERATIONS.md, "Database: container,
backup, restore"):
    schtasks /Create /TN "NewsAggregator DB Backup" /SC DAILY /ST 05:00 ^
        /TR "<repo>\venv\Scripts\python.exe <repo>\scripts\backup_db.py" /RU "<user>"
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Set-ScheduledTask -TaskName "NewsAggregator DB Backup" -Settings $s

A backup job that stops firing is silent by construction, so the 05:30 health
check calls `newest_dump_age_hours()` and alerts when the newest dump is older
than DB_BACKUP_MAX_AGE_HOURS (OPS-01's lesson: the monitor of a job cannot be
the job).
"""
import argparse
import glob
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, REPO_ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except Exception:
    pass

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BACKUP_DIR = os.getenv("DB_BACKUP_DIR", os.path.join(REPO_ROOT, "backups", "pg_dump"))
KEEP = int(os.getenv("DB_BACKUP_KEEP", "14"))
MAX_AGE_HOURS = float(os.getenv("DB_BACKUP_MAX_AGE_HOURS", "48"))
DB_NAME = os.getenv("POSTGRES_DB_NAME", "newsaggregator")
DB_USER = os.getenv("POSTGRES_DB_USER", "postgres")
DB_PORT = os.getenv("POSTGRES_DB_PORT", "5431")
# The tables whose loss is the incident. A dump missing any of them is not a backup.
REQUIRED_TABLES = ("sitemaps", "articles", "chunks", "entities", "entity_mentions", "crawl_log")


class BackupError(RuntimeError):
    pass


def find_container(run=subprocess.run):
    """The container to dump from. DB_CONTAINER wins; otherwise exactly one running
    container must publish DB_PORT -- zero or several is an error, never a guess."""
    explicit = os.getenv("DB_CONTAINER")
    if explicit:
        return explicit
    out = run(
        ["docker", "ps", "--filter", "publish=%s" % DB_PORT, "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise BackupError("docker ps failed: %s" % (out.stderr or "").strip()[:300])
    names = [n for n in out.stdout.split() if n]
    if len(names) != 1:
        raise BackupError(
            "expected exactly one running container publishing port %s, found %d (%s); set DB_CONTAINER"
            % (DB_PORT, len(names), ", ".join(names) or "none")
        )
    return names[0]


def verify_dump(path, container, run=subprocess.run):
    """Raise BackupError unless `pg_restore --list` reads the archive and it holds
    data for every REQUIRED_TABLES entry."""
    with open(path, "rb") as fh:
        out = run(["docker", "exec", "-i", container, "pg_restore", "--list"],
                  stdin=fh, capture_output=True)
    if out.returncode != 0:
        raise BackupError("pg_restore --list rejected the dump: %s"
                          % out.stderr.decode("utf-8", "replace").strip()[:300])
    toc = out.stdout.decode("utf-8", "replace")
    # A TOC line looks like: "3021; 0 16390 TABLE DATA public sitemaps postgres"
    have = {line.split()[-2] for line in toc.splitlines() if " TABLE DATA " in line}
    missing = [t for t in REQUIRED_TABLES if t not in have]
    if missing:
        raise BackupError("dump has no data for: %s" % ", ".join(missing))


def prune(keep, backup_dir=BACKUP_DIR):
    """Delete all but the newest `keep` verified dumps. Returns the deleted paths."""
    dumps = sorted(glob.glob(os.path.join(backup_dir, "%s_*.dump" % DB_NAME)))
    doomed = dumps[:-keep] if keep > 0 else []
    for path in doomed:
        os.remove(path)
    return doomed


def newest_dump_age_hours(backup_dir=BACKUP_DIR, now=None):
    """Hours since the newest verified dump was written, or None when there is none."""
    dumps = glob.glob(os.path.join(backup_dir, "%s_*.dump" % DB_NAME))
    if not dumps:
        return None
    newest = max(os.path.getmtime(p) for p in dumps)
    return ((now if now is not None else time.time()) - newest) / 3600.0


def backup(keep=KEEP, backup_dir=BACKUP_DIR, run=subprocess.run):
    """Dump, verify, prune. Returns the path of the new dump; raises BackupError."""
    os.makedirs(backup_dir, exist_ok=True)
    container = find_container(run)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = os.path.join(backup_dir, "%s_%s.dump" % (DB_NAME, stamp))
    partial = final + ".partial"
    try:
        with open(partial, "wb") as fh:
            # -i without -t: a binary-safe stdout stream, no TTY translation.
            out = run(["docker", "exec", "-i", container, "pg_dump", "-U", DB_USER, "-d", DB_NAME,
                       "-Fc", "-Z", "6"], stdout=fh, stderr=subprocess.PIPE)
        if out.returncode != 0:
            raise BackupError("pg_dump exited %s: %s" % (
                out.returncode, (out.stderr or b"").decode("utf-8", "replace").strip()[:300]))
        verify_dump(partial, container, run)
        os.replace(partial, final)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    deleted = prune(keep, backup_dir)
    logger.info("dump OK: %s (%.1f MB) from %s; pruned %d old dump(s)",
                final, os.path.getsize(final) / 1e6, container, len(deleted))
    return final


def _notify(message):
    try:
        from notify_telegram import send
        send("NewsAggregator DB backup: " + message)
    except Exception as e:  # noqa: BLE001 -- a notifier failure must not mask the backup's own
        logger.warning("could not send notification: %s", e)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", type=int, default=KEEP, help="Verified dumps to retain (default %(default)s)")
    ap.add_argument("--check", action="store_true", help="Only report the newest dump's age; exit 1 if too old")
    args = ap.parse_args(argv)
    if args.check:
        age = newest_dump_age_hours()
        if age is None or age > MAX_AGE_HOURS:
            print("STALE: newest dump is %s" % ("missing" if age is None else "%.1f h old" % age))
            return 1
        print("OK: newest dump is %.1f h old" % age)
        return 0
    if args.keep < 1:
        ap.error("--keep must be at least 1")
    try:
        backup(keep=args.keep)
        return 0
    except Exception as e:  # noqa: BLE001 -- every failure must reach the operator
        logger.exception("backup failed")
        _notify("FAILED: %s: %s" % (type(e).__name__, str(e)[:300]))
        return 1


if __name__ == "__main__":
    sys.exit(main())
