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

Status per check: OK (0), KNOWN (at or below its BASELINE), GROWING (above it).
Since the 2026-09-26 repairs (OPS-04, OPS-25, SRC-54) every baseline is 0: a
stale baseline hid growth up to its size (OPS-25 #174: 1,237 terminal VIVA
orphans read `6529 6529 KNOWN`).

A vector with no article is split by what can still happen to its sitemap
(OPS-25), using repair_store_consistency's classification:
  *_no_articles_terminal  the sitemap can never get an article (rejected_filter,
                          fetch-failure cap, row gone) -- an orphan RAG serves as
                          a hit with nothing behind it. A check, baseline 0.
  *_no_articles_queued    the sitemap is still in the crawl queue and links up
                          when the crawl reaches it. Informational, like the
                          vector totals: it is not a pass/fail check.

l2_over_max_tokens (SYS-137) counts L2 chunk rows longer than CHUNK_MAX_TOKENS words:
a window MiniLM cannot see whole (ADR-008). The chunker never writes one; a row
the crawl adopted from an older chunker (VIVA's June backlog) or a lowered
CHUNK_MAX_TOKENS does. `rechunk_stale_chunks.py` repairs article rows.

faiss_pair_mismatch (SYS-56) counts the levels whose index.faiss and index.pkl
are not one pair (position count differs, a position maps to no document) or
that carry an interrupted save's journal. Every search of such a level returns
the wrong documents. Only the index.faiss header is read, under the level's
save lock, so a save in progress is never mistaken for one.

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

from newscrawler.core.constants import CHUNK_MAX_TOKENS, VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2

# Known, ticketed debris a check may carry without being GROWING. Empty since
# 2026-09-26: every check measured 0 after the repairs (the transient
# PIKIRANRAKYAT crash rows aside, which heal on its next run), and a baseline
# above the real count hides exactly that much new damage. Add an entry only
# with the ticket that owns the debris.
BASELINE = {}


def _load_docstore_sitemap_ids(db_name: str):
    """Sitemap_ids of every document in a FAISS index's docstore, read directly via
    pickle -- no embedding model, no FAISS.load_local, just the on-disk (docstore,
    index_to_docstore_id) tuple LangChain's save_local writes as index.pkl."""
    path = os.path.join(db_name, "index.pkl")
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        docstore, _ = pickle.load(f)
    return _sitemap_ids(docstore)


def _read_level(db_name: str):
    """(sitemap_ids, pair problem or None) of one FAISS level. Read under the
    level's save lock, so the two files are one pair unless a save really was
    torn (SYS-56); read-only, so a journal is reported, not rolled forward."""
    from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation

    if not index_generation.has_index(db_name):
        return [], None
    with index_generation.save_lock(db_name):
        pair = index_generation.read_disk_pair(db_name)
        problem = index_generation.disk_pair_problem(db_name, pair)
    return (_sitemap_ids(pair[1]) if pair else []), problem


def _sitemap_ids(docstore):
    ids = []
    for doc in docstore._dict.values():
        sid = doc.metadata.get("sitemap_id")
        if sid is not None:
            ids.append(int(sid))
    return ids


def compute_divergence(l1_ids, l2_ids, articles_ids, chunks_l1_ids, chunks_l2_ids,
                        pending_embedding_count, terminal_ids=frozenset(), url_category_rows=0,
                        pair_mismatch_levels=0, oversized_l2_rows=0) -> dict:
    """Pure: every count from plain Python sets/ints, no I/O. Kept separate from
    gather_counts() so the arithmetic itself has a fast, DB-free unit test.
    `terminal_ids`: sitemap_ids that can never get an article (OPS-25).
    `url_category_rows`: sitemaps rows whose category is a URL (SRC-53).
    `pair_mismatch_levels`: FAISS levels that are not one pair (SYS-56).
    `oversized_l2_rows`: L2 chunk rows longer than CHUNK_MAX_TOKENS words (SYS-137)."""
    l1_set, l2_set = set(l1_ids), set(l2_ids)
    chunks_any = set(chunks_l1_ids) | set(chunks_l2_ids)
    dup_l1 = {sid for sid, n in Counter(l1_ids).items() if n > 1}
    terminal = set(terminal_ids)
    l1_orphan, l2_orphan = l1_set - articles_ids, l2_set - articles_ids

    return {
        "faiss_pair_mismatch":      pair_mismatch_levels,
        "l1_no_articles_terminal":  len(l1_orphan & terminal),
        "l2_no_articles_terminal":  len(l2_orphan & terminal),
        "l1_no_chunks":             len(l1_set - set(chunks_l1_ids)),
        "l2_no_chunks":             len(l2_set - set(chunks_l2_ids)),
        "articles_no_chunks":       len(articles_ids - chunks_any),
        "l1_not_in_l2":             len(l1_set - l2_set),
        "l1_duplicate_sitemaps":    len(dup_l1),
        "chunks_pending_embedding": pending_embedding_count,
        "chunks_not_in_faiss":      len(chunks_any - (l1_set | l2_set)),
        "sitemaps_url_category":    url_category_rows,
        "l2_over_max_tokens":       oversized_l2_rows,
        # Informational (INFO_KEYS): queued sitemaps' vectors link up when crawled.
        "l1_no_articles_queued":    len(l1_orphan - terminal),
        "l2_no_articles_queued":    len(l2_orphan - terminal),
        # Raw vector counts, not deduplicated sitemap counts -- a duplicate (see
        # l1_duplicate_sitemaps) should visibly inflate this, not disappear into it.
        "l1_total":                 len(l1_ids),
        "l2_total":                 len(l2_ids),
    }


LABELS = {
    "faiss_pair_mismatch":      "FAISS levels whose .faiss and .pkl disagree",
    "l1_no_articles_terminal":  "terminal sitemap_ids in L1 FAISS (no article)",
    "l2_no_articles_terminal":  "terminal sitemap_ids in L2 FAISS (no article)",
    "l1_no_chunks":             "sitemap_ids in L1 FAISS with no chunks row",
    "l2_no_chunks":             "sitemap_ids in L2 FAISS with no chunks row",
    "articles_no_chunks":       "articles rows with no chunks row",
    "l1_not_in_l2":             "sitemap_ids in L1 but not in L2",
    "l1_duplicate_sitemaps":    "sitemap_ids with 2+ L1 vectors",
    "chunks_pending_embedding": "chunks rows with status pending_embedding",
    "chunks_not_in_faiss":      "chunks sitemap_ids not in FAISS (L1 or L2)",
    # SRC-53 (#173): a URL where a section name belongs blinds the category
    # gate, SYS-34's first-save warning and every per-category count. The live
    # checks (probe_branch_scope.py --fail-on-url-keys, the offline fleet test)
    # see only what crawlers list today, never rows already stored.
    "sitemaps_url_category":    "sitemaps rows with a URL as category",
    # SYS-137 (#316): the crawl adopts a queued sitemap's stored chunks as they are.
    "l2_over_max_tokens":       "L2 chunk rows over CHUNK_MAX_TOKENS words",
}
# Order matters for display. INFO_KEYS are context, not pass/fail checks.
CHECK_KEYS = list(LABELS.keys())
INFO_LABELS = {
    "l1_no_articles_queued": "queued sitemap_ids in L1 FAISS (link up later)",
    "l2_no_articles_queued": "queued sitemap_ids in L2 FAISS (link up later)",
}
INFO_KEYS = list(INFO_LABELS.keys()) + ["l1_total", "l2_total"]


def growing_checks(counts: dict) -> list:
    """The checks above their baseline, in display order."""
    return [k for k in CHECK_KEYS if counts[k] > BASELINE.get(k, 0)]


def gather_counts() -> dict:
    """The only I/O in this module: two pickle reads, two index.faiss headers
    and five cheap SQL COUNTs.
    Raises on a real infrastructure failure (missing FAISS dir, DB down) --
    main() decides how to report that; this function does not swallow it, the
    same rule check_crawlers.py's own DB calls follow."""
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    from newscrawler.tools.store_repair import sitemap_state  # one definition of "terminal" (OPS-25, DBT-70)

    l1_ids, l1_problem = _read_level(VECTOR_DB_NAME_L1)
    l2_ids, l2_problem = _read_level(VECTOR_DB_NAME_L2)
    for db_name, problem in ((VECTOR_DB_NAME_L1, l1_problem), (VECTOR_DB_NAME_L2, l2_problem)):
        if problem:
            logger.error("%s is not one index pair: %s (SYS-56)", db_name, problem)

    client = SQLAlchemyClient()
    with client.get_session() as session:
        articles_ids = {r[0] for r in session.execute(text("SELECT DISTINCT sitemap_id FROM articles"))}
        chunks_l1_ids = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 1"))}
        chunks_l2_ids = {r[0] for r in session.execute(
            text("SELECT DISTINCT sitemap_id FROM chunks WHERE chunk_level = 2"))}
        pending = session.execute(
            text("SELECT COUNT(*) FROM chunks WHERE chunk_status = 'pending_embedding'")).scalar()
        url_categories = session.execute(
            text("SELECT COUNT(*) FROM sitemaps WHERE category LIKE 'http%'")).scalar()
        oversized = session.execute(
            text("SELECT COUNT(*) FROM chunks WHERE chunk_level = 2 AND token_count > :m"),
            {"m": CHUNK_MAX_TOKENS}).scalar()
        no_article = (set(l1_ids) | set(l2_ids)) - articles_ids
        state = sitemap_state(session, no_article) if no_article else {}
    # A sitemap row that is gone is terminal too (the repair's own rule).
    terminal = {sid for sid in no_article if state.get(sid, "terminal") == "terminal"}

    return compute_divergence(l1_ids, l2_ids, articles_ids, chunks_l1_ids, chunks_l2_ids, pending, terminal,
                              url_category_rows=url_categories, oversized_l2_rows=oversized,
                              pair_mismatch_levels=sum(1 for p in (l1_problem, l2_problem) if p))


def render_table(counts: dict) -> str:
    rows = ["%-46s %10s %10s %8s" % ("CHECK", "COUNT", "BASELINE", "STATUS"), "-" * 78]
    for key in CHECK_KEYS:
        count = counts[key]
        baseline = BASELINE.get(key, 0)
        status = "OK" if count == 0 else ("KNOWN" if count <= baseline else "GROWING")
        rows.append("%-46s %10d %10d %8s" % (LABELS[key], count, baseline, status))
    rows.append("")
    for key, label in INFO_LABELS.items():
        rows.append("%-46s %10d %10s %8s" % (label, counts[key], "-", "info"))
    rows.append("L1 total vectors: %d   L2 total vectors: %d" % (counts["l1_total"], counts["l2_total"]))
    return "\n".join(rows)


def summary_line(counts: dict) -> str:
    nonzero = [k for k in CHECK_KEYS if counts[k] > 0]
    growing = growing_checks(counts)
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
        "growing": growing_checks(counts),
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
                          "growing": growing_checks(counts),
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
