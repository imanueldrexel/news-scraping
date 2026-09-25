"""OPS-22 (#161): the per-source timeout frees the caller, and a timed-out source
cannot keep writing while the next one runs.

These tests spawn real child processes (about a second each on Windows), because
what they guard is process behaviour: an in-process fake could not show that a
killed source has stopped writing. The crawler inside the child is a stub
(sched_worker_stubs), so no model, DB or network is involved.
"""
import os
import time

import psutil
import pytest

from newscrawler.tools.source_worker import SourceWorker, WorkerInitError

from . import sched_worker_stubs as stubs

# Generous: TerminateProcess + join is milliseconds; the margin absorbs a slow CI box.
EPSILON = 5.0


@pytest.fixture
def worker():
    w = SourceWorker(factory=stubs.stub_factory, init_timeout=60)
    yield w
    w.close()


def _lines(path):
    return path.read_text().count("\n") if path.exists() else 0


class TestTimeoutFreesTheCaller:
    def test_run_returns_within_timeout_plus_epsilon_for_a_source_that_never_ends(self, worker, tmp_path):
        """QA's repro was `sleep(6)` with `timeout=1` taking 6.0 s. The stub here
        never returns at all, so a wait-for-the-worker regression hangs until
        pytest-timeout kills the run instead of passing slowly."""
        worker.start()
        t0 = time.monotonic()
        status, detail = worker.run("HANG:%s" % (tmp_path / "w.log"), "sitemap", timeout=1)
        elapsed = time.monotonic() - t0
        assert status == "timeout" and "killed" in detail
        assert elapsed < 1 + EPSILON, "run() waited %.1fs for a 1s timeout" % elapsed

    def test_a_timed_out_source_stops_writing_before_the_next_source_starts(self, worker, tmp_path):
        """The second half of OPS-22: freeing the caller is not enough if the
        abandoned source keeps writing alongside the next one. The hung stub
        appends to a file every 50 ms. After run() returns, the file must not grow."""
        log = tmp_path / "hung.log"
        worker.start()
        first_pid = worker.pid
        status, _ = worker.run("HANG:%s" % log, "full_text", timeout=1)
        assert status == "timeout"
        assert _lines(log) > 0, "the stub never ran -- the test proves nothing"
        assert not psutil.pid_exists(first_pid) or psutil.Process(first_pid).status() == psutil.STATUS_ZOMBIE
        frozen = _lines(log)
        time.sleep(0.5)  # ten write intervals
        assert _lines(log) == frozen, "the killed source is still writing"

        # ...and the next source runs, in a different process.
        assert worker.run("KOMPAS", "full_text", timeout=30) == ("ok", "")
        assert worker.pid != first_pid and worker.spawned == 2
        assert _lines(log) == frozen


class TestNormalRuns:
    def test_sources_share_one_child_so_the_model_loads_once(self, worker):
        worker.start()
        pid = worker.pid
        assert worker.run("KOMPAS", "sitemap", timeout=30) == ("ok", "")
        assert worker.run("CNBC", "sitemap", timeout=30) == ("ok", "")
        assert worker.pid == pid and worker.spawned == 1

    def test_a_source_that_raises_is_failed_and_the_child_survives(self, worker):
        worker.start()
        pid = worker.pid
        status, detail = worker.run("RAISE", "sitemap", timeout=30)
        assert status == "failed" and "RuntimeError: boom" in detail
        assert worker.alive and worker.pid == pid

    def test_a_child_that_dies_is_failed_and_replaced(self, worker):
        worker.start()
        status, detail = worker.run("DIE", "sitemap", timeout=30)
        assert status == "failed" and "exit code 7" in detail
        assert not worker.alive
        assert worker.run("KOMPAS", "sitemap", timeout=30) == ("ok", "")
        assert worker.spawned == 2

    def test_close_leaves_no_child(self, worker):
        worker.start()
        pid = worker.pid
        worker.close()
        assert not worker.alive
        time.sleep(0.2)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


class TestStart:
    def test_a_crawler_that_cannot_build_raises_with_its_reason(self):
        w = SourceWorker(factory=stubs.failing_factory, init_timeout=60)
        with pytest.raises(WorkerInitError, match="importance_probe.npz"):
            w.start()
        assert not w.alive

    def test_run_reports_an_unbuildable_crawler_as_a_failed_source(self):
        w = SourceWorker(factory=stubs.failing_factory, init_timeout=60)
        status, detail = w.run("KOMPAS", "sitemap", timeout=30)
        assert status == "failed" and "could not start" in detail


def test_the_production_factory_is_the_default():
    from newscrawler.tools import source_worker
    assert SourceWorker.__init__.__defaults__[0] is source_worker.build_crawler_api
    assert os.path.basename(source_worker.__file__) == "source_worker.py"
