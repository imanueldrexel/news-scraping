#!/usr/bin/env python3
"""
OPS-04: the three stores that must agree per sitemap_id -- NEWS_L1/NEWS_L2 FAISS
docstores, the `chunks` table, the `articles` table -- have no invariant check.
Every one of these divergences was silent before this script existed: the RAG UI
happily returns L2 hits for an article-less sitemap, the newsletter silently drops
chunks-less articles, and none of it showed in check_crawlers.py, /api/health, or the
runbook SQL.

Read-only and fast: loads both FAISS docstores via pickle directly (same technique as
scripts/experiments/probe_store_consistency.py, which this supersedes) instead of the
sentence-transformers embedding model, so it needs no GPU/HF download and runs in
seconds regardless of corpus size.

Status: OK (this check is 0) or DIVERGENT (this check is > 0). Unlike
check_crawlers.py, a nonzero count here does not necessarily mean something is
freshly broken -- several checks have known, already-ticketed historical debris (see
--baseline below) that a decision hasn't been executed for yet. This script's job is
to make that debris visible and stop it from growing silently, not to judge it.

Usage:
    python scripts/check_store_consistency.py
    python scripts/check_store_consistency.py --json
    python scripts/check_store_consistency.py --quiet
    python scripts/check_store_consistency.py --report-dir crawler_health

Exit code: 0 = every check is zero, 1 = at least one is nonzero.

Daily/weekly cron: same slot as check_crawlers.py (OPS-01) -- see OPERATIONS.md.
"""
import argparse
import json
import logging
import os
import pickle
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("check_store_consistency")

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2

# 2026-09-16 audit snapshot (#52), kept only as a "did this grow" reference point for
# the checks that still carry known, already-ticketed historical debris. A count at or
# below its baseline is not a new problem; anything above is.
BASELINE = {
    "l1_no_articles":     10680,
    "l2_no_articles":     9497,   # all VIVA, 2026-06-02 (SYS-08's pre-fix debris)
    "l1_no_chunks":       1335,
    "l2_no_chunks":       152,
    "articles_no_chunks": 152,
    "l1_not_in_l2":       1183,   # DBT-20: all MEDIAINDONESIA, 2026-06-02
    "l1_duplicate_sitemaps": 187, # DBT-09: pre-unique-index debris
    "chunks_pending_embedding": 142,
    "chunks_not_in_faiss": 0,
}


def _load_docstore_sitemap_ids(db_name: str):
    """Sitemap_ids of every document in a FAISS index's docstore, read directly via
    pickle -- no embedding model, no FAISS.load_local, just the on-disk (docstore,
    index_to_docstore_id) tuple LangChain's save_local writes as index.pkl."""
    path = os.path.join(db_name, "index.pkl")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        docstore, _ = pickle.load(f)
    ids = []
    for doc in docstore._dict.values():
        sid = doc.metadata.get("sitemap_id")
        if sid is not None:
            ids.append(int(sid))
    return ids


def compute_divergence(l1_ids, l2_ids, articles_ids, chunks_l1_ids, chunks_l2_ids,
                        pending_embedding_count) -> dict:
    """Pure: every count from plain Python sets/ints, no I/O. Kept separate from
    gather_counts() so the arithmetic itself has a fast, DB-free unit test."""
    l1_set, l2_set = set(l1_ids), set(l2_ids)
    chunks_any = set(chunks_l1_ids) | set(chunks_l2_ids)
    dup_l1 = {sid for sid, n in Counter(l1_ids).items() if n > 1}

    return {
        "l1_no_articles":           len(l1_set - articles_ids),
        "l2_no_articles":           len(l2_set - articles_ids),
        "l1_no_chunks":             len(l1_set - set(chunks_l1_ids)),
        "l2_no_chunks":             len(l2_set - set(chunks_l2_ids)),
        "articles_no_chunks":       len(articles_ids - chunks_any),
        "l1_not_in_l2":             len(l1_set - l2_set),
        "l1_duplicate_sitemaps":    len(dup_l1),
        "chunks_pending_embedding": pending_embedding_count,
        "chunks_not_in_faiss":      len(chunks_any - (l1_set | l2_set)),
        # Raw vector counts, not deduplicated sitemap counts -- a duplicate (see
        # l1_duplicate_sitemaps) should visibly inflate this, not disappear into it.
        "l1_total":                 len(l1_ids),
        "l2_total":                 len(l2_ids),
    }


LABELS = {
    "l1_no_articles":           "sitemap_ids in L1 FAISS with no articles row",
    "l2_no_articles":           "sitemap_ids in L2 FAISS with no articles row",
    "l1_no_chunks":             "sitemap_ids in L1 FAISS with no chunks row",
    "l2_no_chunks":             "sitemap_ids in L2 FAISS with no chunks row",
    "articles_no_chunks":       "articles rows with no chunks row",
    "l1_not_in_l2":             "sitemap_ids in L1 but not in L2",
    "l1_duplicate_sitemaps":    "sitemap_ids with 2+ L1 vectors",
    "chunks_pending_embedding": "chunks rows with status pending_embedding",
    "chunks_not_in_faiss":      "chunks sitemap_ids not in FAISS (L1 or L2)",
}
# Order matters for display; l1_total/l2_total are context, not a pass/fail check.
CHECK_KEYS = list(LABELS.keys())


def gather_counts() -> dict:
    """The only I/O in this module: two pickle reads + four cheap SQL COUNTs.
    Raises on a real infrastructure failure (missing FAISS dir, DB down) --
    main() decides how to report that; this function does not swallow it, the
    same rule check_crawlers.py's own DB calls follow."""
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    l1_ids = _load_docstore_sitemap_ids(VECTOR_DB_NAME_L1)
    l2_ids = _load_docstore_sitemap_ids(VECTOR_DB_NAME_L2)

    client = SQLAlchemyClient()
    with client.get_session() as session:
        articles_ids = {r[0] for r in session.execute(text("SELECT DISTINCT sitemap_id FROM articles"))}
        chunks_l1_ids = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 1"))}
        chunks_l2_ids = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 2"))}
        pending = session.execute(
            text("SELECT COUNT(*) FROM chunks WHERE chunk_status = 'pending_embedding'")).scalar()

    return compute_divergence(l1_ids, l2_ids, articles_ids, chunks_l1_ids, chunks_l2_ids, pending)


def render_table(counts: dict) -> str:
    rows = ["%-46s %10s %10s %8s" % ("CHECK", "COUNT", "BASELINE", "STATUS"), "-" * 78]
    for key in CHECK_KEYS:
        count = counts[key]
        baseline = BASELINE.get(key, 0)
        status = "OK" if count == 0 else ("KNOWN" if count <= baseline else "GROWING")
        rows.append("%-46s %10d %10d %8s" % (LABELS[key], count, baseline, status))
    rows.append("")
    rows.append("L1 total vectors: %d   L2 total vectors: %d" % (counts["l1_total"], counts["l2_total"]))
    return "\n".join(rows)


def summary_line(counts: dict) -> str:
    nonzero = [k for k in CHECK_KEYS if counts[k] > 0]
    growing = [k for k in CHECK_KEYS if counts[k] > BASELINE.get(k, 0)]
    if not nonzero:
        return "Store consistency: OK -- all %d checks are zero" % len(CHECK_KEYS)
    line = "Store consistency: %d/%d checks nonzero" % (len(nonzero), len(CHECK_KEYS))
    if growing:
        line += " | GROWING (new, not just known debris): " + ", ".join(growing)
    return line


def write_report(counts: dict, report_dir: str) -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, "store-consistency-" + datetime.now().strftime("%Y-%m-%d") + ".json")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": counts,
        "baseline": BASELINE,
        "growing": [k for k in CHECK_KEYS if counts[k] > BASELINE.get(k, 0)],
        "summary": summary_line(counts),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="FAISS / chunks / articles consistency checker")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout")
    parser.add_argument("--quiet", action="store_true", help="Print only the one-line summary")
    parser.add_argument("--report-dir", default="crawler_health", help="Where to write the dated JSON report")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    try:
        counts = gather_counts()
    except Exception as e:
        print("ERROR: could not gather store-consistency counts: %s" % e, file=sys.stderr)
        return 1

    report_path = write_report(counts, args.report_dir)

    if args.json:
        print(json.dumps({"counts": counts, "baseline": BASELINE,
                          "growing": [k for k in CHECK_KEYS if counts[k] > BASELINE.get(k, 0)],
                          "summary": summary_line(counts)}, ensure_ascii=False, indent=2))
    elif args.quiet:
        print(summary_line(counts))
    else:
        print(render_table(counts))
        print()
        print(summary_line(counts))
        print("Report written to %s" % report_path)

    return 1 if any(counts[k] > 0 for k in CHECK_KEYS) else 0


if __name__ == "__main__":
    sys.exit(main())
