"""QA 2026-10-19: live, read-only checks of SYS-144/145 (ADR-021), SYS-146 and SYS-194. No model call.

  B) topic switches with an adverb NOT on nya_words.ADVERBS, whose name stands only in an object phrase:
     ALONE (no thread), KEPT (a rewriter that echoes the follow-up: the model judged a switch) and FALLBACK
     (no rewriter: the page's path when the rewrite cannot run). Pairs written by QA before the run.
  S) SYS-194: each question six times on one process; the number of distinct card lists.
  D) SYS-146: "ditanya" -> "dita" (a non-clitic stripped): the cards with and without the word.

    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_19\\probe_qa_1019_live.py [B] [S] [D]
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)
from probe_followup_rewrite import _Ledger, on_topic  # noqa: E402

from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.core.summarizer import Reply  # noqa: E402
from newscrawler.web import keywords  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import passes_floor  # noqa: E402

PAIRS = [
    ("Berapa harga emas Antam hari ini?", "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?", ["garuda"]),
    ("Bagaimana kinerja IHSG hari ini?", "Kayaknya ada masalah di Waskita Karya, apa itu?", ["waskita"]),
    ("Apa kata OJK soal kredit perbankan?", "Apa yang mestinya terjadi pada Sritex?", ["sritex"]),
    ("Berapa harga emas Antam hari ini?", "Apa yang aslinya terjadi pada Garuda Indonesia?", ["garuda"]),
    # control: a real object-phrase follow-up (should keep the thread)
    ("Apa keputusan The Fed terbaru?", "Bagaimana dampaknya ke rupiah?", ["fed"]),
]

REPEAT = ["Apa yang dilakukan BI?", "Bagaimana kasus korupsi Pertamina?", "Berapa harga emas Antam hari ini?",
          "Apa kata OJK soal pinjol?", "Bagaimana kabar Sritex?"]

DITANYA = [("Apa jawaban Menkeu saat ditanya soal utang?", ["utang"]), ("Apa jawaban Menkeu soal utang?", ["utang"])]


class _Echo:
    name = "echo"
    priced = False

    def __init__(self, text):
        self.text = text

    def complete(self, prompt):
        return Reply(self.text, 0, 0)


def cards(ranked):
    return [h for h in ranked if passes_floor(h)][:RAG_TOP_K]


def show(label, ranked, counts, words):
    cs = cards(ranked)
    n = sum(1 for h in cs if on_topic(h, words))
    print(f"  {label:8} {n}/{len(cs)} on topic  rewrite={counts.get('rewrite')} fts={counts.get('fts')}")
    for h in cs:
        print(f"      {'+' if on_topic(h, words) else '-'} {h.get('posted_at')} {(h.get('source') or '')[:9]:9} "
              f"{(h.get('title') or '')[:70]}")
    return n


def main():
    parts = set(sys.argv[1:]) or {"B", "S", "D"}
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=_Ledger())
    today = date.today()
    if "B" in parts:
        print("######## B: switches with an unlisted adverb (no model call)")
        for first, follow, words in PAIRS:
            print(f"\n[{first}] -> {follow}")
            qp.rewriter = None
            r, c = qp.candidates(follow, Filters(), today, [])
            show("ALONE", r, c, words)
            qp.rewriter = _Echo(follow)
            r, c = qp.candidates(follow, Filters(), today, [{"question": first}])
            show("KEPT", r, c, words)
            qp.rewriter = None
            r, c = qp.candidates(follow, Filters(), today, [{"question": first}])
            show("FALLBACK", r, c, words)
    if "S" in parts:
        print("\n######## S: SYS-194, six runs per question")
        qp.rewriter = None
        for q in REPEAT:
            lists = []
            for _ in range(6):
                r, _c = qp.candidates(q, Filters(), today, [])
                lists.append(tuple(h.get("sitemap_id") for h in cards(r)))
            print(f"  {len(set(lists))} distinct list(s) in 6 runs: {q}  {lists[0]}")
    if "D" in parts:
        print("\n######## D: SYS-146 'ditanya'")
        qp.rewriter = None
        for q, words in DITANYA:
            print(f"\n{q}  terms={[t.word for t in keywords.terms(q)]}")
            r, c = qp.candidates(q, Filters(), today, [])
            show("ALONE", r, c, words)


if __name__ == "__main__":
    main()
