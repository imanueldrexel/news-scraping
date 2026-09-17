#!/usr/bin/env python3
"""
OPS-04 (#52): refresh the FAISS-vs-chunks-vs-articles divergence snapshot the
2026-09-16 audit took, without waiting for the full check_store_consistency.py
tool the ticket proposes. Read-only -- loads both FAISS docstores directly via
pickle (per the ticket's own repro note) instead of the embedding model, so it
runs in seconds with no GPU/HF download.

Usage:
    python scripts/experiments/probe_store_consistency.py
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def _sitemap_ids_and_counts(db_name):
    with open(os.path.join(db_name, "index.pkl"), "rb") as f:
        docstore, _ = pickle.load(f)
    ids = []
    for doc in docstore._dict.values():
        sid = doc.metadata.get("sitemap_id")
        if sid is not None:
            ids.append(int(sid))
    return ids


def main():
    l1_ids = _sitemap_ids_and_counts(VECTOR_DB_NAME_L1)
    l2_ids = _sitemap_ids_and_counts(VECTOR_DB_NAME_L2)
    l1_set, l2_set = set(l1_ids), set(l2_ids)

    from collections import Counter
    l1_counts = Counter(l1_ids)
    dup_l1_sitemaps = {sid for sid, n in l1_counts.items() if n > 1}

    client = SQLAlchemyClient()
    with client.get_session() as session:
        articles_ids = {r[0] for r in session.execute(text("SELECT DISTINCT sitemap_id FROM articles")).fetchall()}
        chunks_ids_l1 = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 1")).fetchall()}
        chunks_ids_l2 = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 2")).fetchall()}
        chunks_ids_any = chunks_ids_l1 | chunks_ids_l2
        pending = session.execute(
            text("SELECT COUNT(*) FROM chunks WHERE chunk_status = 'pending_embedding'")).scalar()
        articles_no_chunks = session.execute(text("""
            SELECT COUNT(*) FROM articles a
            WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.sitemap_id = a.sitemap_id)
        """)).scalar()

    rows = [
        ("sitemap_ids in L1 FAISS with no articles row", len(l1_set - articles_ids)),
        ("sitemap_ids in L2 FAISS with no articles row", len(l2_set - articles_ids)),
        ("sitemap_ids in L1 FAISS with no chunks row", len(l1_set - chunks_ids_l1)),
        ("sitemap_ids in L2 FAISS with no chunks row", len(l2_set - chunks_ids_l2)),
        ("articles rows with no chunks row", articles_no_chunks),
        ("sitemap_ids in L1 but not in L2", len(l1_set - l2_set)),
        ("sitemap_ids with 2+ L1 vectors", len(dup_l1_sitemaps)),
        ("chunks rows with status pending_embedding", pending),
        ("chunks sitemap_ids not in FAISS (L1 or L2)", len(chunks_ids_any - (l1_set | l2_set))),
    ]

    print(f"{'check':<50} {'2026-09-16':>10} {'now':>10}")
    baseline = {
        "sitemap_ids in L1 FAISS with no articles row": 10680,
        "sitemap_ids in L2 FAISS with no articles row": 9497,
        "sitemap_ids in L1 FAISS with no chunks row": 1335,
        "sitemap_ids in L2 FAISS with no chunks row": 152,
        "articles rows with no chunks row": 152,
        "sitemap_ids in L1 but not in L2": 1183,
        "sitemap_ids with 2+ L1 vectors": 187,
        "chunks rows with status pending_embedding": 142,
        "chunks sitemap_ids not in FAISS (L1 or L2)": 0,
    }
    for label, count in rows:
        print(f"{label:<50} {baseline[label]:>10} {count:>10}")


if __name__ == "__main__":
    main()
