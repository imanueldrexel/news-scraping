"""SYS-61 (#198): which encoder revision built the committed probe's embeddings?

Re-embeds a sample of the gold test rows with the encoder resolved from the local
Hugging Face cache (hf_cache.resolve_model, the path the crawl uses) and compares
them, row by row, with the committed matrix tests/fixtures/probe_test_embeddings.npz
that the probe's gates are recomputed from. Cosine 1.0 on every row means the
cached snapshot is the one the probe was trained against. Read-only; offline.

--faiss NEWS_L1 does the same for a FAISS index: it reads stored vectors
straight from index.faiss (memory-mapped, read-only) and re-embeds their
documents with the MiniLM the crawl resolves. It never loads the index for
writing, so it takes no lock and rolls nothing forward.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_encoder_revision.py [--n 40]
    venv\\Scripts\\python.exe scripts\\experiments\\probe_encoder_revision.py --faiss NEWS_L1 [--n 40]
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from newscrawler.core.importance_probe import ImportanceProbe, build_check_text, embed_for_probe  # noqa: E402
from newscrawler.core.utils.hf_cache import cached_revision, resolve_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=40, help="rows to re-embed (spread over the matrix)")
    parser.add_argument("--faiss", help="check this FAISS index directory instead of the probe")
    args = parser.parse_args()
    if args.faiss:
        return check_faiss(args.faiss, args.n)

    from sentence_transformers import SentenceTransformer

    probe = ImportanceProbe.load()
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    with open(os.path.join(fixtures, "filter_gold.jsonl"), encoding="utf-8") as f:
        test_rows = [r for r in (json.loads(line) for line in f if line.strip()) if r["split"] == "test"]
    cache = np.load(os.path.join(fixtures, "probe_test_embeddings.npz"))
    assert str(cache["encoder"]) == probe.encoder_name and len(test_rows) == int(cache["n"])

    picks = np.linspace(0, len(test_rows) - 1, num=min(args.n, len(test_rows))).astype(int)
    texts = [build_check_text(test_rows[i]["headline"], test_rows[i].get("body_head")) for i in picks]
    path = resolve_model(probe.encoder_name)
    model = SentenceTransformer(path)
    fresh = embed_for_probe(model, texts, model_name=probe.encoder_name)
    stored = cache["X"][picks]
    cos = np.sum(fresh * stored, axis=1) / (np.linalg.norm(fresh, axis=1) * np.linalg.norm(stored, axis=1))
    print(f"encoder {probe.encoder_name} revision {cached_revision(probe.encoder_name)} ({path})")
    print(f"rows {len(picks)}  cosine min {cos.min():.6f}  mean {cos.mean():.6f}  max {cos.max():.6f}")
    return 0 if cos.min() > 0.9999 else 1


def check_faiss(db_name: str, n: int) -> int:
    import pickle

    import faiss
    from langchain_community.embeddings import HuggingFaceEmbeddings

    from newscrawler.core.constants import EMBEDDING_MODEL_HF

    index = faiss.read_index(os.path.join(db_name, "index.faiss"), faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    with open(os.path.join(db_name, "index.pkl"), "rb") as f:
        docstore, index_to_docstore_id = pickle.load(f)
    positions = np.linspace(0, index.ntotal - 1, num=min(n, index.ntotal)).astype(int)
    stored = np.stack([index.reconstruct(int(i)) for i in positions])
    texts = [docstore.search(index_to_docstore_id[int(i)]).page_content for i in positions]
    path = resolve_model(EMBEDDING_MODEL_HF)
    emb = HuggingFaceEmbeddings(model_name=path, encode_kwargs={"normalize_embeddings": True})
    fresh = np.asarray(emb.embed_documents(texts))
    cos = np.sum(fresh * stored, axis=1) / (np.linalg.norm(fresh, axis=1) * np.linalg.norm(stored, axis=1))
    print(f"{db_name}: {index.ntotal} vectors; encoder {EMBEDDING_MODEL_HF} revision "
          f"{cached_revision(EMBEDDING_MODEL_HF)} ({path})")
    print(f"rows {len(positions)}  cosine min {cos.min():.6f}  mean {cos.mean():.6f}  max {cos.max():.6f}")
    return 0 if cos.min() > 0.9999 else 1


if __name__ == "__main__":
    sys.exit(main())
