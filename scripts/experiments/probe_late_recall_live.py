"""SYS-109 (#283): does the production NEWS_L2 index find what an article says late in a long paragraph?

Read-only. `--sample FILE` writes a fixed sample (once): articles holding a paragraph of >= 200 words,
with a late query (the first 8-30-word sentence after word 130 of that paragraph) and an early one
(within its first 60 words). `--measure FILE` runs each query through `ChunkFAISSDatasource.search_l2`
(k=100) and reports the article's rank among the distinct articles returned: recall@1/@5/@20.
Run --measure before and after the re-chunk on the same sample file.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_late_recall_live.py --sample late.json --n 200
    venv\\Scripts\\python.exe scripts\\experiments\\probe_late_recall_live.py --measure late.json
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from probe_encoder_window import sentence_after  # noqa: E402


def sample(path, n, seed):
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(text("""
            SELECT a.sitemap_id, a.extracted_text FROM articles a
            ORDER BY md5(a.sitemap_id::text || :seed) LIMIT :m"""), {"seed": str(seed), "m": n * 20}).fetchall()
    out = []
    for r in rows:
        for para in (r.extracted_text or "").split("\n\n"):
            w = para.split()
            if len(w) < 200:
                continue
            late, early = sentence_after(w, 130), sentence_after(w, 0, 60)
            if late and early:
                out.append({"sitemap_id": r.sitemap_id, "late": late, "early": early})
                break
        if len(out) == n:
            break
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"sampled {len(out)} articles -> {path}")


def measure(path):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
    items = json.load(open(path, encoding="utf-8"))
    ds = ChunkFAISSDatasource()
    print(f"NEWS_L2 vectors: {ds.vs_l2.index.ntotal}")
    for kind in ("late", "early"):
        ranks = []
        for it in items:
            seen = []
            for h in ds.search_l2(it[kind], k=100):
                if h["sitemap_id"] not in seen:
                    seen.append(h["sitemap_id"])
            ranks.append(seen.index(it["sitemap_id"]) + 1 if it["sitemap_id"] in seen else 999)
        n = len(ranks)
        print(f"{kind:5} recall@1={sum(r <= 1 for r in ranks) / n:.3f} @5={sum(r <= 5 for r in ranks) / n:.3f} "
              f"@20={sum(r <= 20 for r in ranks) / n:.3f} (n={n})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample")
    ap.add_argument("--measure")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1091)
    args = ap.parse_args()
    if args.sample:
        sample(args.sample, args.n, args.seed)
    if args.measure:
        measure(args.measure)


if __name__ == "__main__":
    main()
