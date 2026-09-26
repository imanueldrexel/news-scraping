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
the worker is closed. Every script that rewrites FAISS calls
`refuse_if_running()` before its first write (FAISS or SQL), and the one place
all FAISS saves go through, `ChunkFAISSDatasource._atomic_save_local`, refuses
too unless the caller is the lock's owner or its worker (`refuse_foreign_writer`). The lock is a file holding the owner's
pid. A lock whose owner is gone is stale (Task Scheduler's
`ExecutionTimeLimit`, a reboot or a power loss ends the process without running
`finally`) and is taken over; the worker's parent watchdog ends the child
within seconds of the parent, so a dead owner means no worker is left holding
the stores.

OPS-31 (#184): "gone" is not "the pid is dead". Windows reuses pids quickly
(about 5% of a dead run's pids are live again at any moment on this laptop, and
more right after a boot), and a lock held by a reused pid blocked every run
until someone deleted it. So the lock also records its owner's process creation
time, and the owner is alive only while a process with that pid AND that
creation time exists.

The lock only answers "is a scheduled crawl running now?". Whether a save may
replace the index on disk is SYS-53's generation check (index_generation.py).
"""
import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK_PATH = os.path.join(REPO_ROOT, ".scheduled_crawl.lock")


class RunLockHeld(RuntimeError):
    """Another live process holds the scheduled-crawl lock."""


# Two readings of one process's creation time agree; this only absorbs float
# rounding. A reused pid's process was created after the owner died, which is
# at least the run's length after the owner was created.
CREATE_TIME_SLACK_S = 1.0


def _process(pid):
    """(psutil.Process, its creation time) for a live pid, else None."""
    # Not os.kill(pid, 0): on Windows that terminates the process.
    import psutil
    try:
        proc = psutil.Process(int(pid))
        return proc, proc.create_time()
    except (TypeError, ValueError, psutil.NoSuchProcess):
        return None
    except psutil.AccessDenied:
        # We may not read another account's process. The scheduled crawl runs
        # as this account, so such a process cannot be the lock's owner.
        return None


def _is_owner(info, created) -> bool:
    """Is the live process created at `created` the one that wrote `info`?"""
    if "create_time" in info:
        try:
            return abs(created - float(info["create_time"])) <= CREATE_TIME_SLACK_S
        except (TypeError, ValueError):
            return True  # cannot tell: treat as held; the refusal says how to clear it
    # A lock written before OPS-31 has only started_at. Its owner existed before
    # it wrote the lock; a process created after that holds a reused pid.
    try:
        written = datetime.fromisoformat(info["started_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return True
    return created <= written + CREATE_TIME_SLACK_S


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def holder(path=None):
    """The lock's contents ({"pid", "create_time", "started_at", ...}) while the
    process that wrote it is alive, else None: no lock file, unreadable, its pid
    is dead, or its pid now belongs to another process (stale either way)."""
    info = _read(path or LOCK_PATH)
    if not isinstance(info, dict):
        return None
    live = _process(info.get("pid"))
    return info if live and _is_owner(info, live[1]) else None


def refuse_if_running(path=None, allow_pids=()):
    """Raise RunLockHeld when a scheduled crawl is running. Call it in every
    script that rewrites NEWS_L1/NEWS_L2, before the first write. A lock held by
    one of `allow_pids` is not a refusal."""
    path = path or LOCK_PATH
    info = holder(path)
    if info and info.get("pid") not in allow_pids:
        raise RunLockHeld(_held_message(info, path))


def _held_message(info, path) -> str:
    live = _process(info.get("pid"))
    try:
        name = live[0].name() if live else "?"
    except Exception:
        name = "?"
    return ("a scheduled crawl (%s, pid %s, started %s) holds %s; its worker keeps FAISS in memory and its "
            "next flush would overwrite this write. Run this after the crawl ends. If no scheduled crawl is "
            "running (Task Scheduler shows the task Ready, and no python process has run_scheduled_crawl.py "
            "on its command line), the lock is stale: delete %s by hand."
            % (name, info.get("pid"), info.get("started_at"), path, path))


def refuse_foreign_writer(path=None):
    """The FAISS save chokepoint's check: the scheduled run itself (the lock's
    owner) and its worker (the owner's child) may write; anyone else is refused."""
    refuse_if_running(path, allow_pids=(os.getpid(), os.getppid()))


class RunLock:
    """Context manager for the scheduled crawl. Refuses (RunLockHeld) when a live
    process already holds the lock -- two runs would both write FAISS -- and takes
    over a stale one."""

    def __init__(self, path=None, purpose="scheduled crawl"):
        self.path = path or LOCK_PATH
        self.purpose = purpose
        self.acquired = False

    def __enter__(self):
        refuse_if_running(self.path)
        payload = json.dumps({"pid": os.getpid(), "create_time": _process(os.getpid())[1],
                              "purpose": self.purpose,
                              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        # The lock appears complete (written, then linked or renamed into
        # place), so a reader never sees a half-written file.
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        try:
            try:
                # Fails if the file exists, so of two runs that both found no
                # lock only one gets it; the other re-checks below and refuses.
                os.link(tmp, self.path)
            except FileExistsError:
                refuse_if_running(self.path)
                os.replace(tmp, self.path)  # a stale lock: take it over
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
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


def refused_by_run_lock(log) -> bool:
    """For a FAISS-writing script's write path: True (and the reason logged at
    ERROR) when a scheduled crawl holds the lock. Callers exit 2."""
    try:
        refuse_if_running()
    except RunLockHeld as e:
        log.error("refusing to write: %s", e)
        return True
    return False
