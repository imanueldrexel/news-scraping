"""QA 2026-10-12 (second pass), SYS-104/ADR-010: the dev's rewrite probe on pairs QA wrote before the
first run, none of them in the dev's sets. Read-only; the rewrite calls are tallied in memory.

Switch pairs 1, 2 and 5 hold an adverb ending in -nya (sebenarnya, selanjutnya, akhirnya), so the
FALLBACK row shows what the deterministic rule does with them. Switch 4 checks that "pekan ini" of
the KPK question is not carried into an oil-price question.

    venv\\Scripts\\python.exe scripts\\experiments\\qa_2026_10_12b\\probe_qa_followup_pairs.py --fallback
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import probe_followup_rewrite as r  # noqa: E402

r.SETS = {
    "qa_switch": [
        ("Berapa harga emas Antam hari ini?", "Apa yang sebenarnya terjadi pada Garuda Indonesia?", ["garuda"]),
        ("Apa kata OJK soal kredit perbankan?", "Bagaimana nasib Sritex selanjutnya?", ["sritex"]),
        ("Bagaimana kinerja IHSG hari ini?", "Apa kabar program Makan Bergizi Gratis?", ["mbg", "makan bergizi"]),
        ("Siapa yang dipanggil KPK pekan ini?", "Berapa harga minyak dunia?", ["minyak"]),
        ("Kenapa rupiah melemah pekan ini?", "Apakah Danantara akhirnya membeli saham Garuda?", ["danantara"]),
    ],
    "qa_elliptical": [
        ("Apa kabar program Makan Bergizi Gratis?", "Berapa anggarannya tahun depan?", ["mbg", "makan bergizi"]),
        ("Bagaimana kasus korupsi timah?", "Siapa saja tersangkanya?", ["timah"]),
        ("Berapa harga emas Antam hari ini?", "Kenapa naik?", ["emas"]),
        ("Apa keputusan The Fed terbaru?", "Bagaimana dampaknya ke rupiah?", ["fed"]),
        ("Apa kata Menkeu Purbaya soal cukai rokok?", "Kapan aturan tersebut berlaku?", ["cukai"]),
    ],
}

if __name__ == "__main__":
    if "--set" not in sys.argv:
        sys.argv += ["--set", "qa_switch", "--set", "qa_elliptical"]
    r.main()
