#!/usr/bin/env python3
"""
SYS-31 (#86): how well does SemanticImportanceFilter actually separate finance
from everything else, on what the pipeline has already saved?

Scores saved articles exactly the way _crawl_newsdetails_inner does
(`f"{title} {extracted_text[:500]}"` -> max cosine vs INTERESTS, same model,
same threshold) and reports:
  1. the score distribution of a random sample of saved articles -- everything
     saved passed at crawl time, so mass near the threshold is the noise floor;
  2. saved articles per (source, category) for categories that cannot be finance
     (the sitemaps.category label is a free weak label for most sources);
  3. a handful of control texts (recipes, football, gossip, skincare) that a
     finance filter must reject, with their scores.

Read-only. Loads the embedding model (~10 s).

Usage:
    python scripts/experiments/probe_filter_precision.py                 # 600-row sample
    python scripts/experiments/probe_filter_precision.py --sample 2000
    python scripts/experiments/probe_filter_precision.py --website MEDIAINDONESIA --min-id 12700   # DBT-20's 405

2026-09-19 baseline (12,365 saved articles): random 600 -> 53% in [0.35, 0.40),
median 0.396, p90 0.489, 0 below 0.35. >= 700 saved rows sit in off-topic
categories. Control: rendang recipe 0.174, Liga 1 fixture 0.198, skincare 0.222,
bridge inauguration 0.090 (all rejected); "Ria Ricis Nangis Lihat Sapi Kurbannya
Disembelih" 0.421 vs Rupiah (passed -- above the corpus median).
"""
import argparse
import collections
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

import psycopg2
from sentence_transformers import util

from newscrawler.core.constants import INTERESTS
from newscrawler.core.importance_filter import SemanticImportanceFilter

# Same env vars SQLAlchemyClient reads (newscrawler/infrastructure/network/clients/sqlalchemy_client.py).
_PG = dict(host=os.getenv("POSTGRES_DB_HOST", "localhost"), port=os.getenv("POSTGRES_DB_PORT", "5431"),
           user=os.getenv("POSTGRES_DB_USER", "postgres"), password=os.getenv("POSTGRES_DB_PASS", "postgres"),
           dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"))

# Category labels (per source) that cannot be finance/economy. Extend as sources are added.
OFF_TOPIC = {
    "TVONENEWS": ("lifestyle", "religi", "bola", "sport"),
    "SINDONEWS": ("lifestyle", "otomotif", "sports", "edukasi"),
    "CNN": tuple(f"https://www.cnnindonesia.com/{s}/sitemap_news.xml" for s in ("hiburan", "gaya-hidup", "olahraga", "otomotif")),
    "MEDIAINDONESIA": ("fashion", "forum-mahasiswa", "hiburan", "olahraga", "kuliner", "travelista", "sepak-bola", "jelita"),
    "GRIDID": ("Nakita", "Sajian", "Hai", "Motorplus", "Gridoto", "Nova", "Fotokita", "NationalGeographic", "Bobo",
               "Cewekbanget", "Kids", "Parapuan", "Sonora", "Stylo", "Suar", "Intisari"),
    "CNBC": ("lifestyle",),
    "IDXCHANNEL": ("idxtainment",),
    "KOMPAS": ("olahraga", "hiburan", "lifestyle"),
}

CONTROL = [
    "Resep Rendang Daging Sapi Empuk dan Lezat untuk Lebaran. Bahan: 1 kg daging sapi, santan, cabai, bawang merah.",
    "Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih. Selebgram itu tak kuasa menahan tangis saat sapi kesayangannya disembelih di Idul Adha.",
    "6 Langkah Merebus Telur Agar Mudah Dikupas ini, Hasilnya Jadi Cantik. Rebus telur dengan air mendidih selama 10 menit lalu rendam air es.",
    "Jadwal Liga 1: Persib vs Persija Sabtu Malam. Laga big match ini dipastikan berlangsung panas di Stadion GBLA.",
    "Tips Merawat Kulit Wajah Berminyak di Musim Kemarau. Gunakan pembersih wajah dua kali sehari dan pelembap ringan.",
    "Gubernur Jawa Barat Resmikan Jembatan Baru di Cianjur. Peresmian dihadiri ribuan warga yang antusias.",
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=600, help="random saved articles to score")
    ap.add_argument("--website", default=None, help="restrict the sample to one source")
    ap.add_argument("--min-id", type=int, default=None, help="only articles_id >= this (e.g. a recent batch)")
    args = ap.parse_args(argv)

    conn = psycopg2.connect(**_PG)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()

    # 2. off-topic categories that were saved anyway
    total_off = 0
    print("saved articles in categories that cannot be finance:")
    for src, cats in OFF_TOPIC.items():
        cur.execute("SELECT COUNT(*) FROM articles a JOIN sitemaps s ON s.sitemap_id=a.sitemap_id "
                    "WHERE s.sources=%s AND s.category = ANY(%s)", (src, list(cats)))
        n = cur.fetchone()[0]
        total_off += n
        print(f"  {src:<16} {n}")
    cur.execute("SELECT COUNT(*) FROM articles")
    total = cur.fetchone()[0]
    print(f"  TOTAL {total_off} of {total} saved ({100.0 * total_off / max(total, 1):.1f}%) -- a floor; "
          f"regional/politics categories are not counted\n")

    # 1. score distribution
    where = ["a.extracted_text IS NOT NULL", "length(a.extracted_text) > 200"]
    params = []
    if args.website:
        where.append("s.sources = %s"); params.append(args.website)
    if args.min_id is not None:
        where.append("a.articles_id >= %s"); params.append(args.min_id)
    cur.execute(f"SELECT s.sources, s.category, a.meta_data->>'title', a.extracted_text "
                f"FROM articles a JOIN sitemaps s ON s.sitemap_id=a.sitemap_id WHERE {' AND '.join(where)} "
                f"ORDER BY random() LIMIT %s", (*params, args.sample))
    rows = cur.fetchall()

    f = SemanticImportanceFilter(interests=INTERESTS, model_name="paraphrase-multilingual-MiniLM-L12-v2")

    def score(text):
        emb = f.model.encode(" ".join(text.split()[:200]), convert_to_tensor=True)
        sims = util.cos_sim(emb, f.interest_embeddings)[0]
        i = int(sims.argmax())
        return float(sims[i]), INTERESTS[i]

    scored = sorted((score(f"{title} {(text or '')[:500]}") + (src, cat, title)) for src, cat, title, text in rows)
    sc = [x[0] for x in scored]
    if sc:
        print(f"score distribution of {len(sc)} saved articles (threshold {f.threshold}):")
        print(f"  min {sc[0]:.3f}  p10 {sc[len(sc)//10]:.3f}  median {statistics.median(sc):.3f}  "
              f"p90 {sc[9*len(sc)//10]:.3f}  max {sc[-1]:.3f}")
        for lo, hi in ((0, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 1.01)):
            n = sum(1 for x in sc if lo <= x < hi)
            print(f"  [{lo:.2f}, {hi:.2f}): {n:>5}  {100.0 * n / len(sc):5.1f}%")
        print("  lowest 10:")
        for s, best, src, cat, title in scored[:10]:
            print(f"    {s:.3f} {best:<22} {src}/{cat}  {title[:70]}")
        by_cat = collections.Counter((src, cat) for _, _, src, cat, _ in scored)
        print("  sample by (source, category), top 10:", by_cat.most_common(10), "\n")

    # 3. controls
    print("control texts (a finance filter must reject all of these):")
    passed = 0
    for t in CONTROL:
        s, best = score(t)
        flag = "PASSES" if s >= f.threshold else "rejected"
        passed += s >= f.threshold
        print(f"  {s:.3f} [{best}] {flag:<8} {t[:70]}")
    return 1 if passed else 0


if __name__ == "__main__":
    sys.exit(main())
