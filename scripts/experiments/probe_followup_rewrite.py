"""SYS-104 / ADR-010: measure the follow-up rewrite on production, read-only.

For each (first question, follow-up) pair it prints:
  - the follow-up ranked ALONE (the search box);
  - the follow-up AFTER the first question, through QueryProcessor.resolve: the rewrite it got (or the
    fallback), and the top 5 cards;
  - with --fallback, the same AFTER with no rewrite call (the deterministic rule).
A card is on topic when its title or matched paragraph holds one of the pair's subject words
(lower case). The counts are a check on the hand reading, not a replacement for it.

The rewrite calls the configured RAG_LLM_PROVIDER (a few hundred tokens each); their usage is tallied
here, in memory, and never written to api_usage_log. Nothing else is written.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_followup_rewrite.py [--fallback] [--set switch|elliptical|heldout]
"""
import argparse
import os
import sys
from datetime import date
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)

from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import passes_floor  # noqa: E402

# (first question, follow-up, subject words of the FOLLOW-UP's intended subject)
SWITCH = [  # QA 2026-10-12, probe_topic_switch_followups.py
    ("Apa kata OJK soal kredit perbankan?", "Apa itu Danantara?", ["danantara"]),
    ("Berapa harga emas Antam hari ini?", "Siapa Menteri Keuangan sekarang?", ["menkeu", "menteri keuangan", "wamenkeu", "purbaya"]),
    ("Apa keputusan Bank Indonesia soal BI-Rate?", "Bagaimana kasus korupsi Pertamina?", ["pertamina"]),
    ("Bagaimana perkembangan konflik Iran terbaru?", "Di mana terjadi banjir minggu ini?", ["banjir"]),
    ("Kenapa rupiah melemah pekan ini?", "Apa isi UU Ketenagakerjaan yang baru?", ["ketenagakerjaan", "buruh", "pekerja"]),
]
ELLIPTICAL = [  # probe_rag_rank_breakdown.FOLLOWUPS (SYS-104's 7 pairs)
    ("Apa kata OJK soal kredit perbankan?", "Berapa target pertumbuhannya tahun depan?", ["kredit"]),
    ("Apa keputusan Bank Indonesia soal suku bunga terbaru?", "Apa dampaknya ke kredit perbankan?", ["suku bunga", "bi-rate", "bi rate"]),
    ("Bagaimana harga emas Antam hari ini?", "Kalau harga buyback-nya berapa?", ["buyback"]),
    ("Apa isi RUU Ketenagakerjaan yang baru disahkan?", "Bagaimana tanggapan buruh?", ["ketenagakerjaan", "uu cipta", "ruu"]),
    ("Bagaimana perkembangan konflik Iran terbaru?", "Apa dampaknya ke harga minyak?", ["iran", "timur tengah"]),
    ("Siapa yang dipanggil KPK pekan ini?", "Kasusnya tentang apa?", ["kpk"]),
    ("Kenapa rupiah melemah pekan ini?", "Apa yang dilakukan BI?", ["rupiah"]),
]
HELDOUT = [  # written 2026-10-12 before the first run, not tuned on
    ("Bagaimana kinerja IHSG hari ini?", "Saham apa yang paling banyak dibeli asing?", ["asing", "net buy", "investor asing"]),
    ("Apa kabar terbaru soal Danantara?", "Siapa yang memimpinnya?", ["danantara"]),
    ("Berapa inflasi bulan September?", "Bagaimana dengan harga beras?", ["beras"]),
    ("Siapa tersangka korupsi tol MBZ?", "Berapa kerugian negaranya?", ["mbz", "tol", "jalan layang"]),
    ("Bagaimana harga minyak dunia terbaru?", "Apa itu BPJS Kesehatan?", ["bpjs"]),
    ("Kenapa Garuda Indonesia merugi?", "Bagaimana dengan Pertamina?", ["pertamina"]),
]
SETS = {"switch": SWITCH, "elliptical": ELLIPTICAL, "heldout": HELDOUT}


class _Ledger:
    """In-memory usage: the cap is never reached and nothing is written."""
    def __init__(self):
        self.calls = self.input_tokens = self.output_tokens = 0
        self.cost = 0.0

    def get_today_api_usage(self, key):
        return SimpleNamespace(cost_usd=0.0)

    def increment_api_call_count(self, key, input_tokens=0, output_tokens=0, cost_usd=0.0):
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost_usd


def on_topic(hit, words):
    hay = ((hit.get("title") or "") + " " + (hit.get("text_content") or "")).lower()
    return any(w in hay for w in words)


def show(qp, label, question, history, words, today):
    ranked, counts = qp.candidates(question, Filters(), today, history)
    cards = [h for h in ranked if passes_floor(h)][:RAG_TOP_K]
    hits = sum(1 for h in cards if on_topic(h, words))
    print(f"  {label:9} {hits}/{len(cards)} on topic  rewrite={counts['rewrite']} recent={counts['recent']}")
    for h in cards:
        mark = "+" if on_topic(h, words) else "-"
        print(f"      {mark} {h.get('posted_at')} {h.get('source', '')[:10]:10} {(h.get('title') or '')[:80]}")
    return hits, len(cards)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallback", action="store_true", help="also rank AFTER with no rewrite call")
    ap.add_argument("--set", choices=sorted(SETS), action="append")
    args = ap.parse_args()
    import logging
    logging.basicConfig(level=logging.WARNING, format="    %(message)s")
    logging.getLogger("newscrawler.web.query_processor").setLevel(logging.INFO)   # the rewrite lines
    ledger = _Ledger()
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=ledger)
    rewriter = qp.rewriter
    if rewriter is None:
        print("NO REWRITER (RAG_LLM_PROVIDER has no key): every AFTER is the fallback")
    today = date.today()
    for name in args.set or ["switch", "elliptical", "heldout"]:
        totals = {"alone": [0, 0], "after": [0, 0], "fallback": [0, 0]}
        print(f"\n######## {name}")
        for first, follow, words in SETS[name]:
            print(f"\n[{first}] -> {follow}")
            for key, label, history, rw in (("alone", "ALONE", [], rewriter),
                                            ("after", "AFTER", [{"question": first}], rewriter),
                                            ("fallback", "FALLBACK", [{"question": first}], None)):
                if key == "fallback" and not args.fallback:
                    continue
                qp.rewriter = rw
                h, n = show(qp, label, follow, history, words, today)
                totals[key][0] += h
                totals[key][1] += n
            qp.rewriter = rewriter
        print(f"\n== {name}: " + "  ".join(f"{k} {v[0]}/{v[1]}" for k, v in totals.items() if v[1]))
    print(f"\nrewrite calls={ledger.calls} tokens={ledger.input_tokens}/{ledger.output_tokens} cost=${ledger.cost:.5f}")


if __name__ == "__main__":
    main()
