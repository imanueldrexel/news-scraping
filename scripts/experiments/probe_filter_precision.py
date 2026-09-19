#!/usr/bin/env python3
"""
SYS-31 (#86): how well does SemanticImportanceFilter actually separate finance
from everything else, on what the pipeline has already saved?

Uses the SAME deny-list / off-topic anchors the pipeline now uses
(newscrawler/core/importance_filter.py: is_offtopic_category, OFFTOPIC_INTERESTS)
-- not a private copy -- so this probe cannot drift from the production gate.

Reports:
  1. saved articles per (source, category) that a weak category label says
     cannot be finance (`is_offtopic_category`) vs. can be finance
     (WEAK_POSITIVE_CATEGORIES) -- the pre-fix contamination rate.
  2. what the NEW filter (category deny-list + off-topic-anchor margin) does if
     re-run against those same already-saved rows' real text: recall on the
     weak-negative rows (should reject ~all) and retention on the weak-positive
     rows (should keep ~all) -- i.e. does the fix work without regressing.
  3. a control set covering all six titles quoted in SYS-31, scored with
     category=None (worst case: relies on the text-only margin alone).

Read-only. Loads the embedding model (~10 s).

Usage:
    python scripts/experiments/probe_filter_precision.py                 # 600-row sample
    python scripts/experiments/probe_filter_precision.py --sample 2000
    python scripts/experiments/probe_filter_precision.py --website MEDIAINDONESIA --min-id 12700   # DBT-20's 405

2026-09-19 baseline (12,365 saved articles, pre-fix): random 600 -> 53% in
[0.35, 0.40), median 0.396, p90 0.489, 0 below 0.35. >= 700 saved rows sit in
off-topic categories (a floor -- PIKIRANRAKYAT's 3,374 regional rows and JPNN's
politik/daerah/nasional are not counted, no clean weak label). Control:
rendang recipe 0.174, Liga 1 fixture 0.198, skincare 0.222, bridge inauguration
0.090 (all rejected by the old filter too); "Ria Ricis Nangis Lihat Sapi
Kurbannya Disembelih" 0.421 vs Rupiah (passed the OLD filter -- above the
corpus median; category SINDONEWS/lifestyle catches it under the NEW filter).
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
from newscrawler.core.importance_filter import SemanticImportanceFilter, OFFTOPIC_INTERESTS, is_offtopic_category

# Same env vars SQLAlchemyClient reads (newscrawler/infrastructure/network/clients/sqlalchemy_client.py).
_PG = dict(host=os.getenv("POSTGRES_DB_HOST", "localhost"), port=os.getenv("POSTGRES_DB_PORT", "5431"),
           user=os.getenv("POSTGRES_DB_USER", "postgres"), password=os.getenv("POSTGRES_DB_PASS", "postgres"),
           dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"))

# Category values that ARE finance/economy -- the other half of the weak label,
# so precision can be estimated as TP/(TP+FP) instead of just a contamination
# count. Unlisted categories (opini, video, foto, teknologi, daerah, regional
# city/network names, ...) are ambiguous and left unlabeled/excluded, same as
# the ticket's own methodology.
WEAK_POSITIVE_CATEGORIES = {
    "ekonomi", "bisnis", "market-news", "banking", "economics", "economia",
    "finansial", "perbankan", "makro", "bursa", "asuransi", "industri",
    "multifinance", "energi", "agribisnis", "digital_economy", "pajak",
    "infrastruktur", "properti", "riil", "entrepreneur", "ceo_interview",
    "dana_pensiun", "perencanaan_keuangan", "milenomic", "the-founder",
    "cuap-cuap-cuan", "ekbis", "crypto", "syariah",
}

CONTROL = [
    # Negatives: all six titles quoted in SYS-31, scored with category=None so
    # only the text-based margin (not the category deny-list) can save them.
    ("Resep Rendang Daging Sapi Empuk dan Lezat untuk Lebaran. Bahan: 1 kg daging sapi, santan, cabai, bawang merah.", False),
    ("Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih. Selebgram itu tak kuasa menahan tangis saat sapi kesayangannya disembelih di Idul Adha.", False),
    ("6 Langkah Merebus Telur Agar Mudah Dikupas ini, Hasilnya Jadi Cantik. Rebus telur dengan air mendidih selama 10 menit lalu rendam air es.", False),
    ("Jadwal Liga 1: Persib vs Persija Sabtu Malam. Laga big match ini dipastikan berlangsung panas di Stadion GBLA.", False),
    ("Tips Merawat Kulit Wajah Berminyak di Musim Kemarau. Gunakan pembersih wajah dua kali sehari dan pelembap ringan.", False),
    ("Gubernur Jawa Barat Resmikan Jembatan Baru di Cianjur. Peresmian dihadiri ribuan warga yang antusias.", False),
    ("Ruben Onsu Pernah Coba Temui Anak, tapi Berujung Kecewa. Presenter itu mengaku sedih atas kondisi keluarganya.", False),
    ("Alasan Ria Ricis Oplas Hidung, Ternyata Idap Penyakit ini selama 5 Tahun. Ria Ricis buka-bukaan soal operasi plastik yang dijalaninya.", False),
    ("Jessica Mila Kagumi Koleksi Baru Biyan. Artis peran itu memuji rancangan terbaru desainer kondang Biyan Wanaatmadja.", False),
    ("Gubernur Sherly Tjoanda Jadi 'Barista' Kopi. Gubernur Maluku Utara meracik kopi sendiri di acara UMKM lokal.", False),
    # Positives: real economy headlines, must still pass.
    ("Bank Indonesia Naikkan Suku Bunga Acuan 25 Basis Poin. Rapat Dewan Gubernur BI menahan inflasi yang masih tinggi.", True),
    ("IHSG Ditutup Menguat, Saham Perbankan Jadi Penopang. Investor optimistis menyambut laporan keuangan kuartal III.", True),
    ("Stok Beras Bulog Tembus 5,39 Juta Ton, Aman untuk Stabilisasi Harga. Pemerintah pastikan cadangan pangan nasional mencukupi.", True),
    ("Rupiah Melemah ke Level Rp15.800 per Dolar AS Akibat Sentimen Global. Pelaku pasar menanti keputusan suku bunga The Fed.", True),
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

    # 1. score distribution + weak-labeled sample
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

    f_old = SemanticImportanceFilter(interests=INTERESTS, model_name="paraphrase-multilingual-MiniLM-L12-v2")
    f_new = SemanticImportanceFilter(interests=INTERESTS, model_name="paraphrase-multilingual-MiniLM-L12-v2",
                                      offtopic_interests=OFFTOPIC_INTERESTS)
    # Share the loaded model/embeddings between the two instances -- there is no
    # need to load sentence-transformers twice for what is otherwise the same model.
    f_new.model = f_old.model
    f_new.interest_embeddings = f_old.interest_embeddings
    f_new.offtopic_embeddings = f_new.model.encode(f_new.offtopic_interests, convert_to_tensor=True)

    def score(text):
        emb = f_old.model.encode(" ".join(text.split()[:200]), convert_to_tensor=True)
        sims = util.cos_sim(emb, f_old.interest_embeddings)[0]
        i = int(sims.argmax())
        return float(sims[i]), INTERESTS[i]

    scored = sorted((score(f"{title} {(text or '')[:500]}") + (src, cat, title, text) for src, cat, title, text in rows),
                     key=lambda x: x[0])
    sc = [x[0] for x in scored]
    if sc:
        print(f"score distribution of {len(sc)} saved articles (threshold {f_old.threshold}):")
        print(f"  min {sc[0]:.3f}  p10 {sc[len(sc)//10]:.3f}  median {statistics.median(sc):.3f}  "
              f"p90 {sc[9*len(sc)//10]:.3f}  max {sc[-1]:.3f}")
        for lo, hi in ((0, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 1.01)):
            n = sum(1 for x in sc if lo <= x < hi)
            print(f"  [{lo:.2f}, {hi:.2f}): {n:>5}  {100.0 * n / len(sc):5.1f}%")
        by_cat = collections.Counter((src, cat) for _, _, src, cat, _, _ in scored)
        print("  sample by (source, category), top 10:", by_cat.most_common(10), "\n")

    # 2. weak-labeled precision/recall: before (every saved row passed by
    # construction) vs. after (re-run the NEW filter on the same real text).
    neg = [(src, cat, title, text) for _, _, src, cat, title, text in scored if is_offtopic_category(cat)]
    pos = [(src, cat, title, text) for _, _, src, cat, title, text in scored if (cat or "").strip().lower() in WEAK_POSITIVE_CATEGORIES]
    print(f"weak-labeled sample: {len(pos)} positive-category, {len(neg)} negative-category "
          f"(of {len(scored)} sampled; rest unlabeled/ambiguous)")
    if pos or neg:
        precision_before = len(pos) / max(len(pos) + len(neg), 1)
        print(f"  BEFORE (old filter; every sampled row already passed it): "
              f"precision {precision_before:.3f} = {len(pos)}/{len(pos)+len(neg)}  "
              f"({len(neg)} negative-category rows saved anyway)")

        neg_now_rejected = sum(
            1 for src, cat, title, text in neg
            if not f_new.is_important(f"{title} {(text or '')[:500]}", category=cat)
        )
        pos_still_passes = sum(
            1 for src, cat, title, text in pos
            if f_new.is_important(f"{title} {(text or '')[:500]}", category=cat)
        )
        tp, fp = pos_still_passes, len(neg) - neg_now_rejected
        precision_after = tp / max(tp + fp, 1)
        print(f"  AFTER  (new filter, real text re-scored): negative-category rejected "
              f"{neg_now_rejected}/{len(neg)} ({100.0*neg_now_rejected/max(len(neg),1):.1f}%); "
              f"positive-category retained {pos_still_passes}/{len(pos)} "
              f"({100.0*pos_still_passes/max(len(pos),1):.1f}%); "
              f"precision {precision_after:.3f} = {tp}/{tp+fp}\n")
        if neg_now_rejected < len(neg):
            print("  NOT REJECTED (negative-category rows the new filter still passes):")
            for src, cat, title, text in neg:
                if f_new.is_important(f"{title} {(text or '')[:500]}", category=cat):
                    print(f"    {src}/{cat}  {title[:70]}")

    # 3. controls -- every SYS-31-quoted title, category=None (text-only margin).
    print("\ncontrol texts (category=None -- text-only margin must decide):")
    wrong = 0
    for text, should_pass in CONTROL:
        result = f_new.is_important(text, category=None)
        old_score, best = score(text)
        ok = "ok" if result == should_pass else "WRONG"
        wrong += result != should_pass
        print(f"  new={result!s:<5} old_score={old_score:.3f}[{best}] expected={should_pass!s:<5} {ok:<5} {text[:70]}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
