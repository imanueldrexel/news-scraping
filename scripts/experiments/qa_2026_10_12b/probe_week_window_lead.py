"""QA 2026-10-12 (second pass), SYS-138/ADR-012: what the week window puts first when the week is thin.

For each "this week" question it prints the 5 cards WITH the window (QueryProcessor.candidates, as
served) and WITHOUT it (the same rewrite, keyword query and cue, ranked unwindowed: the pre-SYS-138
order). A card marked "kw=0" holds none of the question's keyword anchors. Read-only, no model call.

    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_12b\\probe_week_window_lead.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)

from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.web import keywords  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import passes_floor  # noqa: E402

QUESTIONS = [  # QA's held-out week questions, plus the ticket's two
    "Apa perkembangan kasus korupsi yang ditangani KPK minggu ini?",
    "Bagaimana kinerja IHSG pekan ini?",
    "Berapa harga emas Antam pekan ini?",
    "Apa kebijakan Bank Indonesia minggu ini?",
    "Siapa yang ditangkap polisi minggu ini?",
    "Apa kabar Danantara pekan ini?",
    "Bagaimana kasus Harvey Moeis minggu ini?",
    "Apa kabar Sritex minggu ini?",
    "Bagaimana kasus korupsi Pertamina pekan ini?",
    "Apa perkembangan Garuda Indonesia pekan ini?",
]


def cards(ranked):
    return [h for h in ranked if passes_floor(h)][:RAG_TOP_K]


def line(h):
    return (f"      {h.get('posted_at')} final={h.get('final_score', 0):.3f} sem={h.get('semantic_score', 0):.3f} "
            f"kw={h.get('keyword_score', 0):.2f} {(h.get('title') or '')[:70]}")


def main():
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, rewriter=None)
    today = date.today()
    led_by_kw0 = 0
    for q in QUESTIONS:
        served, counts = qp.candidates(q, Filters(), today)
        query = qp.resolve(q)
        cue = keywords.recency_cue(query.cue_text)
        kq = qp._keyword_query(*query.questions)
        before, _ = qp._ranked(query.text, kq, Filters(), today, cue)
        s, b = cards(served), cards(before)
        week_from = int(today.strftime("%Y%m%d")) - 6
        print(f"\n== {q}  window={counts['window']}")
        print(f"   WITH window (served): kw=0 cards {sum(1 for h in s if not h.get('keyword_score'))}/{len(s)}")
        for h in s:
            print(line(h))
        print(f"   WITHOUT window:        kw=0 cards {sum(1 for h in b if not h.get('keyword_score'))}/{len(b)}")
        for h in b:
            print(line(h))
        if s and not s[0].get("keyword_score") and (not b or b[0].get("keyword_score")):
            led_by_kw0 += 1
    print(f"\nquestions whose served card 1 holds no keyword while the unwindowed card 1 does: {led_by_kw0}/{len(QUESTIONS)}")


if __name__ == "__main__":
    main()
