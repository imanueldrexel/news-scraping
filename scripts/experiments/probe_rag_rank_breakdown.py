"""Where do the search page's candidates land in the re-rank? (QA 2026-10-07: SYS-104..SYS-107)

Runs `QueryProcessor.candidates` -- what `retrieve` ranks before the floor and the cut -- on production,
read-only, with no model call, and prints per question:
- the top N merged hits: final / semantic / keyword score, which retriever found the article (sem / kw /
  both), floor pass, the matched paragraph's word count, date and headline (--detail);
- how many of the 5 sources are keyword-only, how many keyword-only hits pass the floor, and the best rank
  a keyword-only hit reaches;
- how many of the 5 sources matched on a fragment (< 10 words), and the sources' dates.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_rag_rank_breakdown.py --replay
    venv\\Scripts\\python.exe scripts\\experiments\\probe_rag_rank_breakdown.py --detail 14 "Apa itu Danantara?"
    venv\\Scripts\\python.exe scripts\\experiments\\probe_rag_rank_breakdown.py --followups --detail 5

--replay adds replay_rag_answers.QUESTIONS (their filters are ignored: this measures the unfiltered ranking).
--followups runs FOLLOWUPS: each pair's follow-up is ranked with the first question as its history (SYS-104).
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

from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (  # noqa: E402
    ChunkFAISSDatasource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import KEYWORD, QueryProcessor, passes_floor  # noqa: E402

FRAGMENT_WORDS = 10
ORIGIN = {"semantic": "sem ", "keyword": "kw  ", "both": "both"}
# SYS-104: elliptical follow-ups whose own words name the wrong subject or none (QA's OJK pair first).
FOLLOWUPS = [
    ("Apa kata OJK soal kredit perbankan?", "Berapa target pertumbuhannya tahun depan?"),
    ("Apa keputusan Bank Indonesia soal suku bunga terbaru?", "Apa dampaknya ke kredit perbankan?"),
    ("Bagaimana harga emas Antam hari ini?", "Kalau harga buyback-nya berapa?"),
    ("Apa isi RUU Ketenagakerjaan yang baru disahkan?", "Bagaimana tanggapan buruh?"),
    ("Bagaimana perkembangan konflik Iran terbaru?", "Apa dampaknya ke harga minyak?"),
    ("Siapa yang dipanggil KPK pekan ini?", "Kasusnya tentang apa?"),
    ("Kenapa rupiah melemah pekan ini?", "Apa yang dilakukan BI?"),
]


def words(hit):
    return len((hit.get("text_content") or "").split())


def report(qp, label, question, history, today, detail, totals):
    ranked, counts = qp.candidates(question, Filters(), today, history)
    passes = [h for h in ranked if passes_floor(h)]
    cards = passes[:RAG_TOP_K]
    kw_cards = sum(1 for h in cards if h.get("origin") == KEYWORD)
    kw_over_floor = sum(1 for h in passes if h.get("origin") == KEYWORD)
    best_kw = next((i for i, h in enumerate(ranked, 1) if h.get("origin") == KEYWORD), None)
    frag = sum(1 for h in cards if words(h) < FRAGMENT_WORDS)
    totals["cards"] += len(cards)
    totals["keyword_only_cards"] += kw_cards
    totals["keyword_only_over_floor"] += kw_over_floor
    totals["fragment_cards"] += frag
    dates = ",".join(str(h.get("posted_at"))[4:] for h in cards)
    print(f"\n== {label}{question}  semantic={counts['semantic']} fts={counts['fts']} articles={len(ranked)} "
          f"recent={counts['recent']} cards={len(cards)} keyword-only cards={kw_cards} "
          f"keyword-only over floor={kw_over_floor} best keyword-only rank={best_kw} fragment cards={frag} "
          f"card dates(mmdd)={dates}")
    for i, h in enumerate(ranked[:detail], 1):
        ok = "pass" if passes_floor(h) else "drop"
        print(f"{i:3} final={h['final_score']:.3f} sem={h['semantic_score']:.3f} kw={h['keyword_score']:.2f} "
              f"{ORIGIN.get(h.get('origin'), '?   ')} {ok} w={words(h):3} {h.get('posted_at')} "
              f"{h.get('source', '')[:12]:12} {h.get('title', '')[:70]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--replay", action="store_true", help="add replay_rag_answers.QUESTIONS")
    ap.add_argument("--followups", action="store_true", help="rank FOLLOWUPS' follow-ups with their history")
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
        report(qp, "", q, [], today, args.detail, totals)
    if args.followups:
        for first, followup in FOLLOWUPS:
            report(qp, "ALONE     ", followup, [], today, args.detail, totals)
            report(qp, f"AFTER [{first}] ", followup, [{"question": first, "answer": "-"}], today, args.detail, totals)
    print(f"\nTOTAL {totals}")


if __name__ == "__main__":
    main()
