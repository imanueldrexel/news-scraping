"""OPS-22 (#161): crawler stand-ins that run inside a real SourceWorker child.

They live in their own module because the child is spawned: it imports the
factory by module name, so the factory cannot be a closure or a test-local
class. Each factory returns an object with `crawl_website(website, task, deadline=None)`.

Website names drive the behaviour:
  HANG:<path>  append a line to <path> every 50 ms, forever (a hung source that is
               still writing: the thing that must not overlap the next source)
  RAISE        raise RuntimeError("boom")
  DIE          hard-exit the child (OOM, segfault)
  SEGV         a real native access violation (SYS-52's lxml crash, reproduced
               with a NULL read): no Python exception, no `except`, only faulthandler
  LOG          log one INFO line the way the pipeline's funnel does (OPS-27)
  DEADLINE:<path>  write the seconds left before the job's soft deadline to <path> (SYS-139)
  anything else  return at once
"""
import logging
import os
import time


class _StubApi:
    def crawl_website(self, website, task, deadline=None):
        if website.startswith("HANG:"):
            path = website[len("HANG:"):]
            while True:
                with open(path, "a") as fh:
                    fh.write("%d\n" % os.getpid())
                time.sleep(0.05)
        if website == "RAISE":
            raise RuntimeError("boom")
        if website == "DIE":
            os._exit(7)
        if website == "SEGV":
            # A NULL read in C: 0xC0000005 on Windows, SIGSEGV elsewhere. Not
            # ctypes.string_at(0) -- on Windows ctypes turns that into OSError.
            import faulthandler
            faulthandler._read_null()
        if website.startswith("DEADLINE:"):
            # SYS-139: record how far ahead the deadline the child computed lies ("None" without one).
            with open(website[len("DEADLINE:"):], "w") as fh:
                fh.write("None" if deadline is None else "%.3f" % (deadline - time.monotonic()))
        if website == "LOG":
            logging.getLogger("newscrawler.domain.services.crawler_service_impl").info(
                "Full-text crawl finished for LOG: attempted=3 extracted=3 saved=2")
        return None


def stub_factory():
    return _StubApi()


def failing_factory():
    raise FileNotFoundError("importance_probe.npz missing")
