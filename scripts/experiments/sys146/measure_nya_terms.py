"""SYS-146 (#331): does a possessive -nya made into its root ("pemimpinnya" -> "pemimpin") give the
ticket's questions their subject's cards back? Production, read-only, no model call.

Per question: the anchors/names/need and the on-topic cards
  - before: `keywords.terms` with the -nya rules switched off (no adverb is dropped, no root is taken),
    which is the code before ADR-021;
  - now:    `keywords.terms` as shipped (a possessive -nya word is its root when the root keeps 3+
    letters; an adverb from `nya_words.ADVERBS` is no keyword).

    venv\\Scripts\\python.exe scripts\\experiments\\sys146\\measure_nya_terms.py
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)
from probe_followup_rewrite import _Ledger, on_topic  # noqa: E402

from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.web import nya_words  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import passes_floor  # noqa: E402

QUESTIONS = [  # the ticket's five, then held-out ones written before the first run
    ("Apa itu Danantara dan siapa pemimpinnya?", ["danantara"]),
    ("Siapa pemimpin Danantara?", ["danantara"]),
    ("Siapa pemimpinnya Danantara?", ["danantara"]),
    ("Apa itu Danantara dan siapa pemimpin?", ["danantara"]),
    ("Siapa pemilik Sritex dan berapa utangnya?", ["sritex"]),
    ("Berapa saham yang dibeli Danantara dan berapa nilainya?", ["danantara"]),
    ("Siapa direktur utama Garuda Indonesia dan berapa gajinya?", ["garuda"]),
    ("Apa itu BPJS Kesehatan dan berapa iurannya?", ["bpjs"]),
    ("Berapa harga emas Antam dan berapa harga buyback-nya?", ["antam", "emas"]),
    ("Apa yang sebenarnya terjadi pada Garuda Indonesia?", ["garuda"]),
]


class _NyaRulesOff:
    """`keywords.terms` reads nya_words' attributes at call time, so blanking them for a block runs the
    pre-ADR-021 terms."""
    def __enter__(self):
        self.saved = nya_words.ADVERBS, nya_words.possessive_root
        nya_words.ADVERBS, nya_words.possessive_root = frozenset(), (lambda word: None)

    def __exit__(self, *exc):
        nya_words.ADVERBS, nya_words.possessive_root = self.saved


def _row(qp, q, words, today):
    kq = qp._keyword_query(q)
    ranked, counts = qp.candidates(q, Filters(), today, [])
    cards = [h for h in ranked if passes_floor(h)][:RAG_TOP_K]
    n = sum(1 for h in cards if on_topic(h, words))
    return n, (f"{n}/{len(cards)} fts={counts['fts']} anchors={kq.anchors if kq else None} "
               f"names={kq.names if kq else None} need={kq.need if kq else None}")


def main():
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=_Ledger())
    qp.rewriter = None
    today = date.today()
    tot = {"before": 0, "now": 0}
    for q, words in QUESTIONS:
        print(f"\n== {q}")
        with _NyaRulesOff():
            n, line = _row(qp, q, words, today)
        tot["before"] += n
        print(f"  before: {line}")
        n, line = _row(qp, q, words, today)
        tot["now"] += n
        print(f"  now:    {line}")
    print(f"\ntotals: {tot}")


if __name__ == "__main__":
    main()
