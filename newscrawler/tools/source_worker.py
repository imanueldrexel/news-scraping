"""OPS-22 (#161): run one source at a time in a child process that can be killed.

`run_scheduled_crawl.py` used to run each source in a worker *thread* with
`future.result(timeout=...)`. That timeout never freed the caller: the executor's
context exit waited for the thread anyway. Waiting less would not have been a fix
either. Python cannot kill a thread, so an abandoned source keeps running against
the same `CrawlerServiceImpl` (per-run state such as `_source_failure_verdict`) and
the same in-memory FAISS stores as the next source, and both would write
`NEWS_L1/`/`NEWS_L2/`.

A process can be killed. The contract:

* **One model load in the normal case.** The child builds the crawler once
  (`init_crawler()`, ~2 min, ~4 GB) and then runs source after source.
* **A timeout is a kill, not an abandonment.** On timeout the parent terminates
  the child and waits for it to exit *before* it returns. The next source goes
  to a freshly spawned child, which reloads the stores from disk. So a timed-out
  source cannot write concurrently with the next one: by the time `run()`
  returns, its process no longer exists.
* **A soft deadline comes before the kill** (SYS-139, ADR-011). Given
  `soft_margin_s`, a job carries `timeout - soft_margin_s` seconds; the child
  hands `crawl_website` the `time.monotonic()` deadline that gives, and the
  full-text crawl starts no batch that would end after it. The run then
  flushes its vectors and completes; the kill is for a batch that overran.
* **A kill is safe for the stores.** FAISS saves are atomic (DBT-10: tmp dir +
  `os.replace`). Chunk dedup is keyed on SQL rather than FAISS (SYS-17/SYS-25),
  so a kill between the FAISS save and the SQL insert is re-inserted on the
  sitemap's next attempt. A sitemap with no `articles` row stays in the queue.
  The one thing a kill leaves behind is the source's `crawl_log` row in
  `started`. The caller closes it (`run_scheduled_crawl._close_abandoned_log_rows`).
* **An orphan cannot outlive the scheduler.** If the parent is killed (Task
  Scheduler's `ExecutionTimeLimit`), a watchdog thread in the child exits it.
* **What the child says reaches a file** (OPS-27, #176). Given `log_path`, the
  child appends its log records (per-source funnel, filter telemetry, SYS-34
  warnings, tracebacks) to the same file as the parent. Under Task Scheduler
  its stderr is a console window that closes with the process.
* **A native crash leaves a Python stack** (SYS-52, #178). `faulthandler` is
  enabled in the child, writing to that file: an access violation inside lxml
  kills the process before any `except` runs, and Windows kept no dump.

Nothing here imports the pipeline. The child builds it through `factory`, a
module-level callable, so tests can drive the real process machinery with a stub.
"""
import faulthandler
import logging
import multiprocessing
import os
import threading
import time

PARENT_POLL_SECONDS = 5
LOG_FORMAT = "%(asctime)s %(levelname)s [%(processName)s] %(name)s: %(message)s"

logger = logging.getLogger(__name__)

# Windows NTSTATUS names for the exit codes a natively crashed child reports.
_NATIVE_EXIT_CODES = {
    0xC0000005: "access violation",
    0xC00000FD: "stack overflow",
    0xC0000409: "stack buffer overrun",
    0xC0000374: "heap corruption",
}


class WorkerInitError(RuntimeError):
    """The child could not build the crawler (or did not report within the init timeout)."""


def build_crawler_api():
    """The production factory: the same crawler `lambda_handler` builds. Runs in the child."""
    from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
    return init_crawler()


def _watch_parent():
    parent = multiprocessing.parent_process()
    while True:
        time.sleep(PARENT_POLL_SECONDS)
        if parent is None or not parent.is_alive():
            os._exit(3)


# POSIX: multiprocessing reports death by signal as -signum.
_NATIVE_SIGNALS = {-11: "SIGSEGV", -6: "SIGABRT", -7: "SIGBUS"}


def describe_exit_code(code):
    """E.g. `3221225477 = 0xC0000005 access violation` for a native crash, else str(code)."""
    if code is None:
        return "None"
    if code in _NATIVE_SIGNALS:
        return "%s = %s" % (code, _NATIVE_SIGNALS[code])
    unsigned = code & 0xFFFFFFFF
    name = _NATIVE_EXIT_CODES.get(unsigned)
    return "%s = 0x%08X %s" % (code, unsigned, name) if name else str(code)


def is_native_crash(code):
    return code is not None and (code in _NATIVE_SIGNALS or (code & 0xFFFFFFFF) in _NATIVE_EXIT_CODES)


def _configure_child_output(log_path):
    """OPS-27 + SYS-52, child side. Log records go to `log_path` as well as
    stderr; faulthandler writes a crash's Python stack there. Returns the open
    file, which must stay open for faulthandler for the life of the process."""
    if not log_path:
        faulthandler.enable(all_threads=True)
        return None
    fh = open(log_path, "a", encoding="utf-8", buffering=1)
    handler = logging.StreamHandler(fh)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    logging.captureWarnings(True)
    faulthandler.enable(file=fh, all_threads=True)
    return fh


def _worker_loop(conn, factory, log_path=None):
    """Child side: build once, then serve (website, task) jobs until told to stop."""
    _log_file = _configure_child_output(log_path)  # noqa: F841 -- kept open for faulthandler
    threading.Thread(target=_watch_parent, daemon=True, name="parent-watchdog").start()
    try:
        api = factory()
    except BaseException as e:  # noqa: BLE001 -- reported to the parent, which decides
        logger.exception("crawler build failed")
        conn.send(("init_failed", "%s: %s" % (type(e).__name__, str(e)[:300])))
        return
    conn.send(("ready", os.getpid()))
    while True:
        try:
            job = conn.recv()
        except EOFError:
            return
        if job is None:
            return
        website, task, budget_s = job
        deadline = None if budget_s is None else time.monotonic() + budget_s
        logger.info("%s/%s: started in worker pid %d", website, task, os.getpid())
        try:
            api.crawl_website(website, task, deadline=deadline)
            conn.send(("ok", ""))
        except BaseException as e:  # noqa: BLE001 -- the next source must still run
            # The stack goes to the log file; crawl_log keeps 200 chars of message.
            logger.exception("%s/%s failed", website, task)
            conn.send(("failed", "%s: %s" % (type(e).__name__, str(e)[:200])))


class SourceWorker:
    """Parent side. `run()` returns (status, detail); status is ok / failed / timeout,
    or init_failed when no crawler could be built to run the source in (OPS-32:
    not the source's fault, and the caller stops after a few in a row).
    Never raises for a source's own failure. Raises WorkerInitError only from `start()`."""

    def __init__(self, factory=build_crawler_api, init_timeout=1200, log_path=None, soft_margin_s=None):
        """`soft_margin_s` (SYS-139): how long before the kill the source's soft deadline falls;
        None, no soft deadline."""
        self._factory = factory
        self._soft_margin_s = soft_margin_s
        self._init_timeout = init_timeout
        self._log_path = log_path
        self._ctx = multiprocessing.get_context("spawn")
        self._proc = None
        self._conn = None
        self.pid = None
        self.spawned = 0  # how many children this worker has started; >1 means a respawn

    @property
    def alive(self):
        return self._proc is not None and self._proc.is_alive()

    def start(self):
        """Spawn a child and wait until it has built the crawler."""
        if self.alive:
            return
        parent_conn, child_conn = self._ctx.Pipe()
        proc = self._ctx.Process(target=_worker_loop, args=(child_conn, self._factory, self._log_path),
                                 name="source-worker", daemon=True)
        proc.start()
        child_conn.close()
        self._proc, self._conn = proc, parent_conn
        self.spawned += 1
        if not parent_conn.poll(self._init_timeout):
            self._kill()
            raise WorkerInitError("crawler did not start within %ds" % self._init_timeout)
        try:
            kind, payload = parent_conn.recv()
        except EOFError:
            code = self._reap()
            raise WorkerInitError("crawler process exited during start-up (exit code %s)" % describe_exit_code(code))
        if kind != "ready":
            self._reap()
            raise WorkerInitError(payload)
        self.pid = payload

    def run(self, website, task, timeout):
        try:
            self.start()
        except WorkerInitError as e:
            return "init_failed", "crawler could not start: %s" % e
        budget_s = None if self._soft_margin_s is None else max(0.0, timeout - self._soft_margin_s)
        self._conn.send((website, task, budget_s))
        if not self._conn.poll(timeout):
            # The kill is the point: nothing of this source may still be running
            # when the next one starts.
            self._kill()
            return "timeout", "exceeded %ss; worker process killed" % timeout
        try:
            return self._conn.recv()
        except EOFError:
            code = self._reap()
            # SYS-52: "crashed" is a native crash (the stack is in the log file,
            # from faulthandler); anything else is an exit we did not ask for.
            what = "crashed" if is_native_crash(code) else "died"
            return "failed", "worker process %s (exit code %s)" % (what, describe_exit_code(code))

    def close(self):
        if self.alive:
            try:
                self._conn.send(None)
                self._proc.join(30)
            except (OSError, EOFError):
                pass
        if self.alive:
            self._kill()
        else:
            self._reap()

    def _kill(self):
        self._proc.kill()
        self._proc.join()
        self._reap()

    def _reap(self):
        code = None
        if self._proc is not None:
            self._proc.join(10)
            code = self._proc.exitcode
        if self._conn is not None:
            self._conn.close()
        self._proc = self._conn = self.pid = None
        return code
