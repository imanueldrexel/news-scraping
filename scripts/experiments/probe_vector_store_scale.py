#!/usr/bin/env python3
"""
SYS-41 (#127) step 1: how does the FAISS store behave at 1x/2x/5x today's size?

Copies NEWS_L2 (or --index) to a scratch directory and works only on the copy:
nothing under the repo's NEWS_L1/NEWS_L2 is opened for writing, and the copy
is read with FAISS.load_local directly (no save lock, no roll-forward -- a
scratch copy has no journal). Take the copy when no crawl is running.

For each factor it grows the copy to factor x the real vector count by adding
unit-norm random vectors whose docstore entries repeat real chunk texts (so the
pickle grows like the real one), then measures:
  save_local wall time, index.faiss + index.pkl bytes, load_local wall time,
  brute-force search p50/p95 (k=20, 50 random unit queries), and the process
  RSS after load.
Random vectors change nothing about FAISS's flat-index cost; the numbers are
about size, not retrieval quality.

    venv\\Scripts\\python.exe scripts/experiments/probe_vector_store_scale.py --factors 1,2,5 --scratch <dir>

First run + conclusions: EXPERIMENTS.md, 2026-09-29 "SYS-41: FAISS store at 1x/2x/5x, measured".
"""
import argparse
import os
import shutil
import statistics
import sys
import time
import uuid

import numpy as np
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from langchain_community.docstore.document import Document  # noqa: E402
from langchain_community.embeddings import FakeEmbeddings  # noqa: E402
from langchain_community.vectorstores import FAISS  # noqa: E402


def sizes(d):
    return {f: os.path.getsize(os.path.join(d, f)) for f in ("index.faiss", "index.pkl")}


def grow(vs, target, rng):
    """Add vectors until ntotal == target, reusing real texts/metadata."""
    base = list(vs.docstore._dict.values())
    dim = vs.index.d
    need = target - vs.index.ntotal
    batch = 20000
    while need > 0:
        n = min(batch, need)
        vecs = rng.standard_normal((n, dim)).astype("float32")
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        ids = [str(uuid.uuid4()) for _ in range(n)]
        docs = [Document(page_content=base[i % len(base)].page_content, metadata=dict(base[i % len(base)].metadata))
                for i in range(n)]
        start = vs.index.ntotal
        vs.index.add(vecs)
        vs.docstore.add(dict(zip(ids, docs)))
        vs.index_to_docstore_id.update({start + j: ids[j] for j in range(n)})
        need -= n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=os.path.join(ROOT, "NEWS_L2"))
    ap.add_argument("--factors", default="1,2,5")
    ap.add_argument("--scratch", required=True)
    args = ap.parse_args()
    emb = FakeEmbeddings(size=384)
    rng = np.random.default_rng(20260929)
    proc = psutil.Process()

    src = os.path.join(args.scratch, "source")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(args.index, src, ignore=shutil.ignore_patterns("*.bak", "*.lock"))
    vs = FAISS.load_local(src, emb, allow_dangerous_deserialization=True)
    n0 = vs.index.ntotal
    print(f"{args.index}: {n0} vectors, dim {vs.index.d}, {type(vs.index).__name__}; files {sizes(src)}", flush=True)

    print(f"{'factor':>6} {'vectors':>9} {'faiss MB':>9} {'pkl MB':>8} {'save s':>7} {'load s':>7} "
          f"{'p50 ms':>7} {'p95 ms':>7} {'RSS GB':>7}", flush=True)
    for factor in [int(f) for f in args.factors.split(",")]:
        grow(vs, n0 * factor, rng)
        out = os.path.join(args.scratch, f"x{factor}")
        shutil.rmtree(out, ignore_errors=True)
        t = time.monotonic()
        vs.save_local(out)
        save_s = time.monotonic() - t
        sz = sizes(out)
        del vs
        t = time.monotonic()
        vs = FAISS.load_local(out, emb, allow_dangerous_deserialization=True)
        load_s = time.monotonic() - t
        rss = proc.memory_info().rss / 1e9
        q = rng.standard_normal((50, vs.index.d)).astype("float32")
        q /= np.linalg.norm(q, axis=1, keepdims=True)
        lat = []
        for row in q:
            t = time.perf_counter()
            vs.index.search(row[None, :], 20)
            lat.append((time.perf_counter() - t) * 1000)
        lat.sort()
        print(f"{factor:6} {vs.index.ntotal:9} {sz['index.faiss'] / 1e6:9.0f} {sz['index.pkl'] / 1e6:8.0f} "
              f"{save_s:7.1f} {load_s:7.1f} {statistics.median(lat):7.1f} {lat[int(len(lat) * 0.95) - 1]:7.1f} "
              f"{rss:7.2f}", flush=True)
        shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(src, ignore_errors=True)


if __name__ == "__main__":
    main()
