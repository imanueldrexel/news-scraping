"""SYS-53 (#182): can a crawl that loaded FAISS during the scheduled run
overwrite the run's vectors once the run lock is released?

Two sibling processes (neither is the other's child) over a tmp index built
with FakeEmbeddings, with the run lock in the same tmp dir, so nothing here
touches NEWS_L1/NEWS_L2 or the real lock:

  sched   takes RunLock, loads the index, waits for manual to load, adds
          "run" and saves (allowed: it owns the lock), waits, releases.
  manual  loads while the lock is held, adds "manual" once sched has saved,
          saves under the lock (RunLockHeld), and saves again after release.

Before SYS-53 the second manual save was allowed and the final disk was
['seed', 'manual']: the run's vector was gone. After it, that save is refused
with StaleIndexError and the disk keeps ['seed', 'run'].

    venv\\Scripts\\python.exe scripts\\experiments\\repro_stale_index_overwrite.py [--dir DIR]

Prints one JSON line: {"events": [...], "final_disk": [...]}. Exit 0 when the
run's vector is still on disk, 1 when it was overwritten.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _signal(d, name):
    open(os.path.join(d, name), "w").close()


def _wait(d, name, timeout=120):
    deadline = time.time() + timeout
    while not os.path.exists(os.path.join(d, name)):
        if time.time() > deadline:
            raise TimeoutError("no %s signal" % name)
        time.sleep(0.05)


def _setup(d):
    from langchain_community.embeddings import FakeEmbeddings
    from newscrawler.tools import run_lock
    run_lock.LOCK_PATH = os.path.join(d, "scheduled_crawl.lock")
    return FakeEmbeddings(size=8), os.path.join(d, "NEWS_L1")


def _texts(vs):
    return sorted(doc.page_content for doc in vs.docstore._dict.values())


def _log(d, role, event):
    with open(os.path.join(d, "events.log"), "a", encoding="utf-8") as f:
        f.write("%s: %s\n" % (role, event))


def role_sched(d):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource)
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    from newscrawler.tools.run_lock import RunLock
    emb, idx = _setup(d)
    with RunLock(purpose="scheduled crawl (repro)"):
        vs = load_index(idx, emb)
        _signal(d, "locked")
        _wait(d, "manual_loaded")
        vs.add_texts(["run"])
        ChunkFAISSDatasource._atomic_save_local(vs, idx)
        _log(d, "sched", "saved under its lock")
        _signal(d, "sched_saved")
        _wait(d, "manual_tried_under_lock")
    _log(d, "sched", "lock released")
    _signal(d, "released")


def role_manual(d):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource)
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import (
        StaleIndexError, load_index)
    from newscrawler.tools.run_lock import RunLockHeld
    emb, idx = _setup(d)
    _wait(d, "locked")
    vs = load_index(idx, emb)
    _signal(d, "manual_loaded")
    _wait(d, "sched_saved")
    vs.add_texts(["manual"])
    try:
        ChunkFAISSDatasource._atomic_save_local(vs, idx)
        _log(d, "manual", "save under the lock ALLOWED")
    except RunLockHeld:
        _log(d, "manual", "save under the lock refused (RunLockHeld)")
    _signal(d, "manual_tried_under_lock")
    _wait(d, "released")
    try:
        ChunkFAISSDatasource._atomic_save_local(vs, idx)
        _log(d, "manual", "save after release ALLOWED")
    except StaleIndexError:
        _log(d, "manual", "save after release refused (StaleIndexError)")


def orchestrate(d):
    from langchain_community.vectorstores import FAISS
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource)
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
    emb, idx = _setup(d)
    seed = FAISS.from_texts(["seed"], emb)
    index_generation.track(seed, idx, None)
    ChunkFAISSDatasource._atomic_save_local(seed, idx)

    me = os.path.abspath(__file__)
    procs = [subprocess.Popen([sys.executable, me, "--dir", d, "--role", role], cwd=ROOT)
             for role in ("sched", "manual")]
    rcs = [p.wait(timeout=300) for p in procs]
    final = _texts(FAISS.load_local(idx, emb, allow_dangerous_deserialization=True))
    with open(os.path.join(d, "events.log"), encoding="utf-8") as f:
        events = f.read().splitlines()
    return {"events": events, "final_disk": final, "child_rcs": rcs}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--role", choices=("sched", "manual"))
    args = ap.parse_args(argv)
    if args.role:
        (role_sched if args.role == "sched" else role_manual)(args.dir)
        return 0
    d = args.dir or tempfile.mkdtemp(prefix="sys53_repro_")
    os.makedirs(d, exist_ok=True)
    out = orchestrate(d)
    print(json.dumps(out))
    return 0 if "run" in out["final_disk"] and not any(out["child_rcs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
