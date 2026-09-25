"""OPS-22 (#161): crawler stand-ins that run inside a real SourceWorker child.

They live in their own module because the child is spawned: it imports the
factory by module name, so the factory cannot be a closure or a test-local
class. Each factory returns an object with `crawl_website(website, task)`.

Website names drive the behaviour:
  HANG:<path>  append a line to <path> every 50 ms, forever (a hung source that is
               still writing: the thing that must not overlap the next source)
  RAISE        raise RuntimeError("boom")
  DIE          hard-exit the child (OOM, segfault)
  anything else  return at once
"""
import os
import time


class _StubApi:
    def crawl_website(self, website, task):
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
        return None


def stub_factory():
    return _StubApi()


def failing_factory():
    raise FileNotFoundError("importance_probe.npz missing")
