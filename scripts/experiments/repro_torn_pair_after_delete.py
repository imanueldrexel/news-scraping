r"""SYS-56 (#190): a kill in the middle of a FAISS save that deleted vectors (SYS-54's
discard) must not leave a pair whose positions map to the wrong documents.

    venv\Scripts\python.exe scripts\experiments\repro_torn_pair_after_delete.py [--kill-after N | --all]

Tmp index only, with one-hot embeddings so a query for d<i> must return d<i>. The run
lock is pointed at a nonexistent file so the chokepoint allows the save. Steps:
save d0..d5, load it through index_generation.load_index, delete sitemap 1's vector
(what discard() does), then save with the process "killed" (SystemExit) right after
filesystem step N of the save (a replace, rename or copy), then load the index the
way every production reader does (load_index) and query d0, d2..d5.

The default kill point is QA's: right after index.pkl is replaced. Before SYS-56 the
load returned `index.ntotal=6 index_to_docstore_id=5`, `d2 -> d3`, `d3 -> d4`,
`d5 -> KeyError`. `--all` tries every step. The unit test
(tests/unit/test_chunk_faiss_atomic_save.py::TestKilledMidSave) runs this module.

Prints one JSON line per kill point; exit 0 when every query is right.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

N_DOCS = 6
DELETED = 1


class Killed(BaseException):
    """What a worker kill looks like to the save: nothing after it runs."""


def _embeddings():
    from langchain_core.embeddings import Embeddings

    class OneHot(Embeddings):
        """d<i> -> unit vector e_i, so a query for d<i> must return d<i>."""
        def _v(self, t):
            v = [0.0] * 8
            v[int(t[1:])] = 1.0
            return v

        def embed_documents(self, texts):
            return [self._v(t) for t in texts]

        def embed_query(self, text):
            return self._v(text)

    return OneHot()


def _fs_steps():
    """The filesystem calls a save makes, which a kill can fall between."""
    return (("os.replace", os.replace), ("os.rename", os.rename), ("shutil.copy2", shutil.copy2))


def seed(root):
    from langchain.schema import Document
    from langchain_community.vectorstores import FAISS
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource)
    from newscrawler.tools import run_lock

    run_lock.LOCK_PATH = os.path.join(root, "no_such_run.lock")
    emb = _embeddings()
    db = os.path.join(root, "NEWS_L2")
    vs = FAISS.from_documents([Document(page_content="d%d" % i, metadata={"sitemap_id": i})
                               for i in range(N_DOCS)], emb)
    index_generation.track(vs, db, None)
    ChunkFAISSDatasource._atomic_save_local(vs, db)
    return db, emb


def save_killed_after(db, emb, kill_after):
    """Delete sitemap DELETED's vector and save, raising Killed right after
    filesystem step `kill_after` (0-based; None = never). Returns the steps run."""
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
        ChunkFAISSDatasource)

    vs = index_generation.load_index(db, emb)
    vs.delete([k for k, d in vs.docstore._dict.items() if d.metadata["sitemap_id"] == DELETED])
    steps = []

    def wrap(name, real):
        def step(src, dst, *a, **k):
            out = real(src, dst, *a, **k)
            steps.append("%s -> %s" % (name, os.path.relpath(str(dst), os.path.dirname(db))))
            if kill_after is not None and len(steps) - 1 == kill_after:
                raise Killed("killed after step %d" % kill_after)
            return out
        return step

    patches = [patch(target, wrap(target, real)) for target, real in _fs_steps()]
    for p in patches:
        p.start()
    try:
        ChunkFAISSDatasource._atomic_save_local(vs, db)
    except Killed:
        pass
    finally:
        for p in patches:
            p.stop()
    return steps


def read_back(db, emb):
    """Load as production does and query every remaining document."""
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation

    try:
        vs = index_generation.load_index(db, emb)
    except Exception as e:  # noqa: BLE001 -- the result is the report
        return {"load": "ERROR %r" % e, "ok": False}
    queries = {}
    for i in range(N_DOCS):
        if i == DELETED:
            continue
        q = "d%d" % i
        try:
            queries[q] = vs.similarity_search(q, k=1)[0].page_content
        except Exception as e:  # noqa: BLE001
            queries[q] = "ERROR %r" % e
    texts = sorted(d.page_content for d in vs.docstore._dict.values())
    generation = "new" if "d%d" % DELETED not in texts else "old"
    return {"ntotal": vs.index.ntotal, "mapped": len(vs.index_to_docstore_id), "generation": generation,
            "queries": queries, "ok": all(q == hit for q, hit in queries.items())}


def run(root, kill_after):
    db, emb = seed(root)
    steps = save_killed_after(db, emb, kill_after)
    out = read_back(db, emb)
    out.update(kill_after=kill_after, steps=steps)
    return out


def count_steps(root):
    """How many filesystem steps an uninterrupted save of the repro makes."""
    db, emb = seed(root)
    return len(save_killed_after(db, emb, None))


def qa_kill_point(root):
    """The step right after index.pkl is replaced: QA's original kill point."""
    db, emb = seed(root)
    steps = save_killed_after(db, emb, None)
    return next(i for i, s in enumerate(steps) if s.startswith("os.replace") and s.endswith("index.pkl"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kill-after", type=int)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)

    def fresh():
        return tempfile.mkdtemp(prefix="sys56_repro_")

    if args.all:
        points = range(count_steps(fresh()))
    else:
        points = [args.kill_after if args.kill_after is not None else qa_kill_point(fresh())]
    ok = True
    for n in points:
        root = fresh()
        try:
            out = run(root, n)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        print(json.dumps(out))
        ok = ok and out["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
