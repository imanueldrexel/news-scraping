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
* **A kill is safe for the stores.** FAISS saves are atomic (DBT-10: tmp dir +
  `os.replace`). Chunk dedup is keyed on SQL rather than FAISS (SYS-17/SYS-25),
  so a kill between the FAISS save and the SQL insert is re-inserted on the
  sitemap's next attempt. A sitemap with no `articles` row stays in the queue.
  The one thing a kill leaves behind is the source's `crawl_log` row in
  `started`. The caller closes it (`run_scheduled_crawl._close_abandoned_log_rows`).
* **An orphan cannot outlive the scheduler.** If the parent is killed (Task
  Scheduler's `ExecutionTimeLimit`), a watchdog thread in the child exits it.

Nothing here imports the pipeline. The child builds it through `factory`, a
module-level callable, so tests can drive the real process machinery with a stub.
"""
import multiprocessing
import os
import threading
import time
import traceback

PARENT_POLL_SECONDS = 5


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


def _worker_loop(conn, factory):
    """Child side: build once, then serve (website, task) jobs until told to stop."""
    threading.Thread(target=_watch_parent, daemon=True, name="parent-watchdog").start()
    try:
        api = factory()
    except BaseException as e:  # noqa: BLE001 -- reported to the parent, which decides
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
        website, task = job
        try:
            api.crawl_website(website, task)
            conn.send(("ok", ""))
        except BaseException as e:  # noqa: BLE001 -- the next source must still run
            traceback.print_exc()
            conn.send(("failed", "%s: %s" % (type(e).__name__, str(e)[:200])))


class SourceWorker:
    """Parent side. `run()` returns (status, detail); status is ok / failed / timeout.
    Never raises for a source's own failure. Raises WorkerInitError only from `start()`."""

    def __init__(self, factory=build_crawler_api, init_timeout=1200):
        self._factory = factory
        self._init_timeout = init_timeout
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
        proc = self._ctx.Process(target=_worker_loop, args=(child_conn, self._factory),
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
            raise WorkerInitError("crawler process exited during start-up (exit code %s)" % code)
        if kind != "ready":
            self._reap()
            raise WorkerInitError(payload)
        self.pid = payload

    def run(self, website, task, timeout):
        try:
            self.start()
        except WorkerInitError as e:
            return "failed", "crawler could not start: %s" % e
        self._conn.send((website, task))
        if not self._conn.poll(timeout):
            # The kill is the point: nothing of this source may still be running
            # when the next one starts.
            self._kill()
            return "timeout", "exceeded %ss; worker process killed" % timeout
        try:
            return self._conn.recv()
        except EOFError:
            code = self._reap()
            return "failed", "worker process died (exit code %s)" % code

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
