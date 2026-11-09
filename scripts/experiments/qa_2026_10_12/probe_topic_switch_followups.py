"""QA 2026-10-12 (SYS-104): a follow-up that changes the subject. SYS-104 retrieves every follow-up
with the thread's last two questions; this ranks non-elliptical follow-ups ALONE and AFTER an
unrelated first question, read-only, no model call (probe_rag_rank_breakdown.report).

    venv\Scripts\python.exe scripts\experiments\qa_2026_10_12\probe_topic_switch_followups.py
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)

SWITCHES = [
    ("Apa kata OJK soal kredit perbankan?", "Apa itu Danantara?"),
    ("Berapa harga emas Antam hari ini?", "Siapa Menteri Keuangan sekarang?"),
    ("Apa keputusan Bank Indonesia soal BI-Rate?", "Bagaimana kasus korupsi Pertamina?"),
    ("Bagaimana perkembangan konflik Iran terbaru?", "Di mana terjadi banjir minggu ini?"),
    ("Kenapa rupiah melemah pekan ini?", "Apa isi UU Ketenagakerjaan yang baru?"),
]

if __name__ == "__main__":
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=None)
    totals = {"cards": 0, "keyword_only_cards": 0, "keyword_only_over_floor": 0, "fragment_cards": 0}
    for first, follow in SWITCHES:
        p.report(qp, "ALONE     ", follow, [], date.today(), 5, totals)
        p.report(qp, f"AFTER [{first}] ", follow, [{"question": first, "answer": "-"}], date.today(), 5, totals)
