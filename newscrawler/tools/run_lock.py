"""OPS-26 (#175): a lock held for the whole scheduled crawl, not per source.

The scheduled crawl's worker loads NEWS_L1/NEWS_L2 once and keeps them in memory
across every source of the run (DBT-10 makes that in-memory copy authoritative
until each source's flush). Any other process that rewrites FAISS during the run
is overwritten by the next flush: deleted vectors come back while their deleted
`chunks` rows do not. That is the half-and-half divergence OPS-04's first
`--apply` produced.

The FAISS-writing scripts used to guard on a `crawl_log` row in `started`. That
row exists only while one *source* runs. It is absent while the worker loads the
stores (~30 s at the start of a run, and again after an OPS-22 kill respawns
it) and between two sources, which is exactly when a repair could slip in.

So `run_scheduled_crawl.py` holds this lock from before `worker.start()` until
the worker is closed, and every script that rewrites FAISS calls
`refuse_if_running()` before it writes. The lock is a file holding the owner's
pid. A lock whose pid is no longer alive is stale (Task Scheduler's
`ExecutionTimeLimit` kills the process without running `finally`) and is taken
over; the worker's parent watchdog ends the child within seconds of the parent,
so a dead owner means no worker is left holding the stores.
"""
import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK_PATH = os.path.join(REPO_ROOT, ".scheduled_crawl.lock")


class RunLockHeld(RuntimeError):
    """Another live process holds the scheduled-crawl lock."""


def _pid_alive(pid) -> bool:
    # Not os.kill(pid, 0): on Windows that terminates the process.
    import psutil
    try:
        return psutil.pid_exists(int(pid))
    except (TypeError, ValueError):
        return False


def holder(path=LOCK_PATH):
    """The lock's contents ({"pid", "started_at", ...}) when a live process holds
    it, else None (no lock file, unreadable, or its owner is dead)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    return info if _pid_alive(info.get("pid")) else None


def refuse_if_running(path=LOCK_PATH):
    """Raise RunLockHeld when a scheduled crawl is running. Call it in every
    script that rewrites NEWS_L1/NEWS_L2, before the first write."""
    info = holder(path)
    if info:
        raise RunLockHeld(
            "a scheduled crawl (pid %s, started %s) holds %s; its worker keeps FAISS in memory "
            "and its next flush would overwrite this write. Run it after the crawl ends."
            % (info.get("pid"), info.get("started_at"), path))


class RunLock:
    """Context manager for the scheduled crawl. Refuses (RunLockHeld) when a live
    process already holds the lock -- two runs would both write FAISS -- and takes
    over a stale one."""

    def __init__(self, path=LOCK_PATH, purpose="scheduled crawl"):
        self.path = path
        self.purpose = purpose
        self.acquired = False

    def __enter__(self):
        refuse_if_running(self.path)
        payload = json.dumps({"pid": os.getpid(), "purpose": self.purpose,
                              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        # Write-then-rename, so a reader never sees a half-written file.
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, self.path)
        self.acquired = True
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def release(self):
        if not self.acquired:
            return
        self.acquired = False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                mine = json.load(f).get("pid") == os.getpid()
        except (OSError, ValueError):
            return
        if mine:
            try:
                os.remove(self.path)
            except OSError:
                pass
