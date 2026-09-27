r"""SYS-56 (#190) QA repro: a kill between the index.pkl and index.faiss swaps, after a
delete (SYS-54 discard), leaves a pair whose positions map to the wrong documents.

    venv\Scripts\python.exe scripts\experiments\repro_torn_pair_after_delete.py
epro_torn_pair_after_delete.py

Tmp index only; the run lock is pointed at a nonexistent file so the chokepoint allows the save."""
import os, sys, shutil, tempfile
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from langchain.schema import Document
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation


class OneHot(Embeddings):
    """doc 'd<i>' -> unit vector e_i, so a query for d<i> must return d<i>."""
    N = 8
    def _v(self, t):
        v = [0.0] * self.N; v[int(t[1:])] = 1.0; return v
    def embed_documents(self, texts): return [self._v(t) for t in texts]
    def embed_query(self, t): return self._v(t)


import newscrawler.tools.run_lock as rl; rl.LOCK_PATH = os.path.join(tempfile.gettempdir(), "no_such_run.lock")
emb = OneHot()
root = tempfile.mkdtemp()
db = os.path.join(root, "NEWS_L2")
docs = [Document(page_content="d%d" % i, metadata={"sitemap_id": i}) for i in range(6)]
vs = FAISS.from_documents(docs, emb)
index_generation.track(vs, db, None)
ChunkFAISSDatasource._atomic_save_local(vs, db)          # consistent pair on disk

vs = index_generation.load_index(db, emb)
ids = [k for k, d in vs.docstore._dict.items() if d.metadata["sitemap_id"] == 1]
vs.delete(ids)                                             # what discard() does

real_replace = os.replace
def killed_after_pkl(src, dst):
    real_replace(src, dst)
    if dst.endswith("index.pkl"):
        raise SystemExit("worker killed between the two swaps")
os.replace = killed_after_pkl
try:
    ChunkFAISSDatasource._atomic_save_local(vs, db)
except SystemExit as e:
    print("simulated:", e)
os.replace = real_replace

torn = FAISS.load_local(db, emb, allow_dangerous_deserialization=True)
print("index.ntotal=%d  index_to_docstore_id=%d" % (torn.index.ntotal, len(torn.index_to_docstore_id)))
for q in ("d2", "d3", "d5"):
    try:
        hit = torn.similarity_search(q, k=1)[0].page_content
    except Exception as e:
        hit = "ERROR %r" % e
    print("query %s -> %s  %s" % (q, hit, "OK" if hit == q else "WRONG"))
shutil.rmtree(root, ignore_errors=True)
