"""SYS-60 repro (QA 2026-09-28): SYS-59 lets a writer finish its OWN interrupted
commit, but when another process finishes it first (the web app's load, any
script's load_index), the writer's next save is refused as stale and its
unsaved vectors are dropped.

Runs in a tmp dir with FakeEmbeddings, with the run lock pointed into it, so it
touches neither NEWS_L1/NEWS_L2 nor the real lock.

    venv\Scripts\python.exe scripts\experiments\repro_foreign_rollforward_stale.py

Bug present:  "A's save 2: StaleIndexError" and final ['a', 'b'] ('c' lost).
Fixed:        "A's save 2: OK" and final ['a', 'b', 'c'].
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langchain.schema import Document  # noqa: E402
from langchain_community.embeddings import FakeEmbeddings  # noqa: E402
from langchain_community.vectorstores import FAISS  # noqa: E402

from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation as ig  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (  # noqa: E402
    ChunkFAISSDatasource as C)
from newscrawler.tools import run_lock  # noqa: E402


def main():
    d = tempfile.mkdtemp()
    run_lock.LOCK_PATH = os.path.join(d, "scheduled_crawl.lock")
    emb = FakeEmbeddings(size=8)
    db = os.path.join(d, "NEWS_L1")
    seed = FAISS.from_documents([Document(page_content="a")], emb)
    ig.track(seed, db, None)
    C._atomic_save_local(seed, db)

    a = ig.load_index(db, emb)  # the crawl worker's copy
    a.add_documents([Document(page_content="b")])
    real = os.replace

    def flaky(src, dst):
        # A scanner (or the web app's /api/health mmap) holds index.faiss during the roll-forward.
        if dst.endswith("index.faiss") and ".commit" in src:
            raise PermissionError("index.faiss held open by another process")
        return real(src, dst)

    os.replace = flaky
    try:
        C._atomic_save_local(a, db)
    except PermissionError as e:
        print("A's save 1:", e)
    finally:
        os.replace = real
    print("journal left:", os.path.isdir(ig.journal_dir(db)))

    b = ig.load_index(db, emb)  # another process loads: it rolls A's journal forward
    print("B sees", sorted(x.page_content for x in b.docstore._dict.values()))

    a.add_documents([Document(page_content="c")])
    try:
        C._atomic_save_local(a, db)
        print("A's save 2: OK")
    except ig.StaleIndexError as e:
        print("A's save 2: StaleIndexError --", str(e)[:100])
    print("final", sorted(x.page_content for x in ig.load_index(db, emb).docstore._dict.values()))


if __name__ == "__main__":
    main()
