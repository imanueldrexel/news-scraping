"""Where do the search page's candidates land in the re-rank? (QA 2026-10-07: SYS-105, SYS-106, SYS-107)

Runs `retrieve`'s own steps (FAISS L2 + the keyword half → _merge → _attach_metadata → _re_rank) on
production, read-only, with no model call, and prints per question:
- the top N merged hits: final / semantic / keyword score, floor pass, the matched paragraph's word count,
  date and headline (--detail);
- how many of the 5 sources are keyword-only (semantic 0), how many keyword-only hits pass the floor, and
  the best rank a keyword-only hit reaches;
- how many of the 5 sources matched on a fragment (< 10 words).

    venv\\Scripts\\python.exe scripts\\experiments\\probe_rag_rank_breakdown.py --replay
    venv\\Scripts\\python.exe scripts\\experiments\\probe_rag_rank_breakdown.py --detail 14 "Apa itu Danantara?"

--replay adds replay_rag_answers.QUESTIONS (their filters are ignored: this measures the unfiltered ranking).
Loads MiniLM + both FAISS indexes (~20 s). Safe while the crawl runs: it never writes.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from datetime import date  # noqa: E402

from newscrawler.core.constants import RAG_MIN_KEYWORD_COVERAGE, RAG_MIN_SEMANTIC_SCORE, RAG_TOP_K  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (  # noqa: E402
    ChunkFAISSDatasource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import SEARCH_K, QueryProcessor  # noqa: E402

FRAGMENT_WORDS = 10


def words(hit):
    return len((hit.get("text_content") or "").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--replay", action="store_true", help="add replay_rag_answers.QUESTIONS")
    ap.add_argument("--detail", type=int, default=0, help="print the top N merged hits per question")
    args = ap.parse_args()
    questions = list(args.questions)
    if args.replay:
        from replay_rag_answers import QUESTIONS
        questions = [q["query"] for q in QUESTIONS] + questions

    qp = QueryProcessor(ChunkFAISSDatasource(), SQLAlchemyClient(), summarizer=None, usage=None)
    today = date.today()
    totals = {"cards": 0, "keyword_only_cards": 0, "keyword_only_over_floor": 0, "fragment_cards": 0}
    for q in questions:
        sem = qp.faiss_ds.search_l2(q, k=SEARCH_K)
        fts = qp._fts_search(q, SEARCH_K, Filters(), today)
        merged = qp._re_rank(qp._attach_metadata(qp._merge(sem, fts)), today)
        passes = [h for h in merged if h["semantic_score"] >= RAG_MIN_SEMANTIC_SCORE
                  or h["keyword_score"] >= RAG_MIN_KEYWORD_COVERAGE]
        cards = passes[:RAG_TOP_K]
        kw_only = [h for h in passes if h["semantic_score"] == 0]
        best_kw_only = next((i for i, h in enumerate(merged, 1) if h["semantic_score"] == 0), None)
        frag = sum(1 for h in cards if words(h) < FRAGMENT_WORDS)
        totals["cards"] += len(cards)
        totals["keyword_only_cards"] += sum(1 for h in cards if h["semantic_score"] == 0)
        totals["keyword_only_over_floor"] += len(kw_only)
        totals["fragment_cards"] += frag
        print(f"\n== {q}  semantic={len(sem)} fts={len(fts)} articles={len(merged)}  "
              f"cards={len(cards)} keyword-only cards={sum(1 for h in cards if h['semantic_score'] == 0)} "
              f"keyword-only over floor={len(kw_only)} best keyword-only rank={best_kw_only} fragment cards={frag}")
        for i, h in enumerate(merged[:args.detail], 1):
            ok = "pass" if h in passes else "drop"
            print(f"{i:3} final={h['final_score']:.3f} sem={h['semantic_score']:.3f} kw={h['keyword_score']:.2f} {ok} "
                  f"w={words(h):3} {h.get('posted_at')} {h.get('source', '')[:12]:12} {h.get('title', '')[:70]}")
    print(f"\nTOTAL {totals}")


if __name__ == "__main__":
    main()
