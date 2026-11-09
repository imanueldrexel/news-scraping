"""SYS-109 (#283): which way of embedding a long L2 paragraph lets search find what it says late?

MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`) truncates at 128 tokens (~97 words); L2 chunks run to
450 words. Read-only on production; no index is written.

Sample: SOURCES long L2 paragraphs (>= 200 words, of an article) and DISTRACTORS random L2 paragraphs.
Per source, two queries taken from its own text:
  late  -- the first 8-30-word sentence that starts after word 130 (outside MiniLM's window today);
  early -- the first 8-30-word sentence inside the first 60 words (inside it today: a regression check).
Each option embeds the pool (sources + distractors) its way and each query; the source's rank among the
pool gives recall@1/@5 and MRR. Options:
  minilm128   today's vectors (max_seq_length 128)
  minilm256 / minilm512   the same model, a longer window (its position table has 512)
  win<N>      each paragraph split into <= N-word windows (overlap 20), embedded at 128; a paragraph
              scores its best window (what chunking to the window would give). 128 MiniLM tokens hold
              ~83 Indonesian words (median): win70 fits 95% of windows, win90 only 18%
  e5base / e5large   intfloat/multilingual-e5-* at 512 tokens ("query: " / "passage: ")
Throughput (paragraphs/s on this CPU) is extrapolated to the corpus.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_encoder_window.py [--sources 300] [--distractors 4000]
        [--options minilm128,minilm256,minilm512,win90,e5base]
"""
import argparse
import os
import random
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import numpy as np  # noqa: E402
from sqlalchemy import text  # noqa: E402

from newscrawler.core.utils.hf_cache import resolve_model  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SENTENCE = re.compile(r"[^.!?]+[.!?]")


def sentence_after(words, start, stop=None):
    """The first 8-30-word sentence that starts at or after word `start` (and before `stop`)."""
    body = " ".join(words)
    offset = 0
    for m in SENTENCE.finditer(body):
        first = len(body[:m.start()].split())
        n = len(m.group(0).split())
        if first >= start and (stop is None or first < stop) and 8 <= n <= 30:
            return m.group(0).strip()
        offset += 1
    return None


def windows(t, size=90, overlap=20):
    w = t.split()
    out, i = [], 0
    while True:
        out.append(" ".join(w[i:i + size]))
        if i + size >= len(w):
            return out
        i += size - overlap


def load_sample(n_sources, n_distractors, seed):
    with SQLAlchemyClient().get_session() as s:
        long_rows = s.execute(text("""
            SELECT c.chunk_id, c.text_content FROM chunks c
            WHERE c.chunk_level = 2 AND c.token_count >= 200
              AND EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = c.sitemap_id)
            ORDER BY md5(c.chunk_id::text || :seed) LIMIT :n"""), {"n": n_sources * 3, "seed": str(seed)}).fetchall()
        other = s.execute(text("""
            SELECT c.chunk_id, c.text_content FROM chunks c
            WHERE c.chunk_level = 2 AND c.token_count >= 15
              AND EXISTS (SELECT 1 FROM articles a WHERE a.sitemap_id = c.sitemap_id)
            ORDER BY md5(c.chunk_id::text || :seed || 'd') LIMIT :n"""), {"n": n_distractors, "seed": str(seed)}).fetchall()
    sources = []
    for r in long_rows:
        w = r.text_content.split()
        late, early = sentence_after(w, 130), sentence_after(w, 0, 60)
        if late and early:
            sources.append((r.chunk_id, r.text_content, late, early))
        if len(sources) == n_sources:
            break
    ids = {cid for cid, *_ in sources}
    distractors = [(r.chunk_id, r.text_content) for r in other if r.chunk_id not in ids]
    return sources, distractors


class Encoder:
    def __init__(self, name):
        from sentence_transformers import SentenceTransformer
        self.name = name
        if name.startswith(("minilm", "win")):
            self.model = SentenceTransformer(resolve_model(MINILM))
            self.model.max_seq_length = 128 if name.startswith("win") else int(name[len("minilm"):])
            self.q, self.p = "", ""
        else:
            repo = {"e5base": "intfloat/multilingual-e5-base", "e5large": "intfloat/multilingual-e5-large"}[name]
            self.model = SentenceTransformer(resolve_model(repo))
            self.model.max_seq_length = 512
            self.q, self.p = "query: ", "passage: "

    def encode(self, texts, prefix):
        return self.model.encode([prefix + t for t in texts], batch_size=32, normalize_embeddings=True,
                                 show_progress_bar=False)


def evaluate(name, sources, distractors):
    enc = Encoder(name)
    pool = [(cid, t) for cid, t, *_ in sources] + distractors
    owner, texts = [], []
    for i, (_, t) in enumerate(pool):
        for piece in (windows(t, int(name[3:])) if name.startswith("win") else [t]):
            owner.append(i)
            texts.append(piece)
    start = time.perf_counter()
    vecs = enc.encode(texts, enc.p)
    seconds = time.perf_counter() - start
    owner = np.asarray(owner)
    out = {"name": name, "pool_vectors": len(texts), "paragraphs_per_s": len(pool) / seconds}
    for kind, col in (("late", 2), ("early", 3)):
        q = enc.encode([s[col] for s in sources], enc.q)
        sims = q @ vecs.T                                       # queries x vectors
        best = np.full((len(sources), len(pool)), -1.0, dtype="float32")
        np.maximum.at(best.T, owner, sims.T)                    # a paragraph's best vector
        ranks = []
        for qi in range(len(sources)):
            target = best[qi, qi]
            ranks.append(int((best[qi] > target).sum()) + 1)
        ranks = np.asarray(ranks)
        out[kind] = {"r@1": float((ranks <= 1).mean()), "r@5": float((ranks <= 5).mean()),
                     "mrr": float((1.0 / ranks).mean())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=int, default=300)
    ap.add_argument("--distractors", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=109)
    ap.add_argument("--options", default="minilm128,minilm256,minilm512,win90,e5base")
    ap.add_argument("--corpus-paragraphs", type=int, default=372938, help="L2 vectors, for the time estimate")
    args = ap.parse_args()
    sources, distractors = load_sample(args.sources, args.distractors, args.seed)
    print(f"sources={len(sources)} distractors={len(distractors)}")
    for name in args.options.split(","):
        r = evaluate(name, sources, distractors)
        hours = args.corpus_paragraphs / r["paragraphs_per_s"] / 3600
        print(f"{name:10} late r@1={r['late']['r@1']:.3f} r@5={r['late']['r@5']:.3f} mrr={r['late']['mrr']:.3f} | "
              f"early r@1={r['early']['r@1']:.3f} r@5={r['early']['r@5']:.3f} mrr={r['early']['mrr']:.3f} | "
              f"{r['paragraphs_per_s']:.0f} paragraphs/s, pool vectors {r['pool_vectors']}, "
              f"corpus ~{hours:.1f} h", flush=True)


if __name__ == "__main__":
    main()
