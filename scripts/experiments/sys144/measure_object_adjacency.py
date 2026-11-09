"""SYS-144/145 send-back (#408/#409/#410, ADR-022): do QA's 10-19 switches stay alone, without losing the thread
elsewhere?

Production, read-only, NO model call (as measure_name_gate.py): the `kept` path is forced with a rewriter that
echoes the follow-up, the fallback with no rewriter. Per pair: ALONE, then KEPT and FALLBACK under
  - head: ADR-021 as shipped at 8cd85d6 (every object phrase masked, preposition + up to 4 words);
  - now:  the shipped code (ADR-022: a -nya word right after "yang" is no reference unless a verb; the object
          phrase runs to its clause's end).
Run 1 (2026-10-20) measured a rejected candidate as "now": only a reference word's ADJACENT object phrase is
masked. qa_1019 6/20 -> 17/19, switch_1020 11/16 -> 16/16, but risk 24/30 -> 1/30 (EXPERIMENTS.md 2026-10-20).

QA_1019 are QA's four held-out switches (#408). RISK and SWITCH_1020 were written 2026-10-20 BEFORE the first
run: RISK pairs refer to the thread through a reference whose object phrase is NOT adjacent ("harganya naik di
Jakarta"), the shape the new rule gives up; SWITCH_1020 are switches of QA's shape with other adverbs.
OBJECT and the two 10-18 held-out sets are measure_name_gate.py's, kept as regression sets.

    venv\\Scripts\\python.exe scripts\\experiments\\sys144\\measure_object_adjacency.py
"""
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import measure_name_gate as g  # noqa: E402  (loads .env, puts the repo on sys.path)

from newscrawler.core import story_words  # noqa: E402
from newscrawler.web import followup, nya_words  # noqa: E402

QA_1019 = [  # scripts/experiments/qa_2026_10_19/defects/test_327_object_name_unlisted_adverb.py
    ("Berapa harga emas Antam hari ini?", "Apa yang harusnya dilakukan pemerintah terhadap Garuda Indonesia?",
     ["garuda"]),
    ("Berapa harga emas Antam hari ini?", "Apa yang aslinya terjadi pada Garuda Indonesia?", ["garuda"]),
    ("Apa kata OJK soal kredit perbankan?", "Apa yang mestinya terjadi pada Sritex?", ["sritex"]),
    ("Bagaimana kinerja IHSG hari ini?", "Kayaknya ada masalah di Waskita Karya, apa itu?", ["waskita"]),
]
RISK = [  # thread pairs whose reference is not followed by its object phrase; on-topic = the thread's subject
    ("Berapa harga cabai hari ini?", "Kenapa harganya naik di Jakarta?", ["cabai"]),
    ("Apa keputusan The Fed terbaru?", "Kapan keputusannya berlaku di Indonesia?", ["fed"]),
    ("Siapa Menteri Keuangan yang baru?", "Apa yang dia katakan tentang utang di DPR?",
     ["menteri keuangan", "menkeu", "purbaya"]),
    ("Apa isi kebijakan tarif impor Trump?", "Kapan aturannya mulai berlaku bagi Indonesia?", ["tarif"]),
    ("Kenapa saham GoTo anjlok?", "Apakah sahamnya juga turun di Bursa Efek Indonesia?", ["goto"]),
    ("Bagaimana kasus korupsi timah?", "Berapa total kerugiannya menurut BPK?", ["timah"]),
]
SWITCH_1020 = [  # QA's shape with adverbs on no list; on-topic = the follow-up's own subject
    ("Apa keputusan The Fed terbaru?", "Apa yang harusnya dilakukan investor terhadap saham BBCA?", ["bbca", "bca"]),
    ("Kenapa harga beras naik?", "Apa yang benarnya terjadi di Waskita Karya?", ["waskita"]),
    ("Berapa harga emas Antam hari ini?", "Apa yang semestinya diputuskan untuk Sritex?", ["sritex"]),
    ("Apa kata OJK soal kredit perbankan?", "Gimana jadinya nasib investor di Danantara?", ["danantara"]),
]
SETS = [("qa_1019", QA_1019), ("risk", RISK), ("switch_1020", SWITCH_1020), ("object", g.OBJECT),
        ("heldout_1018", g.HELDOUT_1018), ("heldout_1018b", g.HELDOUT_1018B)]

_HEAD_OBJECT_PHRASE = re.compile(r"\b(?:ke|kepada|terhadap|bagi|untuk|pada|di|atas)\s+((?:\S+\s+){0,3}\S+)",
                                 re.IGNORECASE)


def _head_refers_to_thread(question, previous):
    """followup.refers_to_thread at 8cd85d6 (ADR-021), with that commit's `_references`."""
    refs = [m for m in followup._REFERENCE.finditer(question or "")
            if not m.group(0).lower().endswith("nya") or nya_words.is_reference(m.group(0))]
    if not refs:
        return False
    thread = story_words.vocabulary(" ".join(previous))
    if not story_words.names(question) - thread:
        return True
    outside = list(question)
    for m in _HEAD_OBJECT_PHRASE.finditer(question):
        outside[m.start(1):m.end(1)] = " " * (m.end(1) - m.start(1))
    if story_words.names("".join(outside)) - thread:
        return False
    return not story_words.names(question[:refs[0].start()]) - thread


# The adverb list at 8cd85d6: SYS-146's send-back adds QA's words to it, which would hide the follow-up rule on
# exactly the pairs that test it. Both columns run on this list, so they differ by the rule alone.
ADVERBS_8CD85D6 = nya_words.ADVERBS - {"harusnya", "mestinya", "baiknya", "benarnya", "betulnya", "patutnya",
                                       "aslinya", "kayaknya", "keliatannya"}


def main():
    nya_words.ADVERBS = ADVERBS_8CD85D6
    qp = g.p.QueryProcessor(g.p.ChunkFAISSDatasource(), g.p.SQLAlchemyClient(), summarizer=None, usage=g._Ledger())
    today = date.today()
    shipped = followup.resolve
    variants = [("head", g._resolve_by(_head_refers_to_thread)), ("now", shipped)]
    cols = ["alone"] + [f"{k}_{v}" for v, _ in variants for k in ("kept", "fb")]
    try:
        for name, pairs in SETS:
            tot = {c: [0, 0] for c in cols}
            print(f"\n######## {name}")
            for first, follow, words in pairs:
                hist = [{"question": first}]
                row = {}
                qp.rewriter = None
                followup.resolve = shipped
                row["alone"] = g._count(qp, follow, [], words, today)
                for vname, fn in variants:
                    followup.resolve = fn
                    qp.rewriter = g._Echo(follow)
                    row[f"kept_{vname}"] = g._count(qp, follow, hist, words, today)
                    qp.rewriter = None
                    row[f"fb_{vname}"] = g._count(qp, follow, hist, words, today)
                followup.resolve = shipped
                print(f"[{first}] -> {follow}")
                print("   " + "  ".join(f"{c}={row[c][0]}/{row[c][1]}({row[c][2][:6]})" for c in cols))
                for c in cols:
                    tot[c][0] += row[c][0]
                    tot[c][1] += row[c][1]
            print(f"== {name}: " + "  ".join(f"{c} {v[0]}/{v[1]}" for c, v in tot.items()))
    finally:
        followup.resolve = shipped


if __name__ == "__main__":
    main()
