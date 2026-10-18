"""SYS-144/145 (#327/#328): does "a follow-up that names a subject its thread lacks is its own question"
hold where the adverb list cannot? Production, read-only, NO model call: the `kept` path is forced with a
rewriter that echoes the follow-up (what ADR-014 does when the model judges a switch), the fallback with
no rewriter.

Per pair: ALONE; then KEPT and FALLBACK under each rule, patched into `followup.resolve` for the run only.
The keyword terms are the current ones in every column (SYS-146), so the columns differ by the follow-up rule:
  - before:    the rule before ADR-021: any reference word outside the old 26-word adverb list;
  - gate:      before, and the follow-up names nothing the thread lacks (story_words.names(q) minus
               story_words.vocabulary(thread) is empty);
  - gate_obj:  as gate, but a name inside "ke/terhadap/bagi/kepada <up to 3 words>" is not the follow-up's
               own subject ("Bagaimana dampaknya ke IHSG?" is still about the thread);
  - gate_obj2: as gate_obj, also "pada/untuk/di/atas" and up to 4 words (added after run 1);
  - gate_ana:  as gate_obj2, and a new name before the reference word counts even in an object phrase;
  - now:       the shipped code (ADR-021: gate_ana + the wider adverb list, first reference decides).
OBJECT pairs were written 2026-10-19 ~04:00 before the first run: the -nya word points at the thread and the
only name is the object it affects -- the shape a name gate gets wrong.

    venv\Scripts\python.exe scripts\experiments\sys144\measure_name_gate.py
"""
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import probe_rag_rank_breakdown as p  # noqa: E402  (loads .env, puts the repo on sys.path)
from probe_followup_rewrite import ELLIPTICAL, HELDOUT, SWITCH, _Ledger, on_topic  # noqa: E402

from newscrawler.core import story_words  # noqa: E402
from newscrawler.core.constants import RAG_TOP_K  # noqa: E402
from newscrawler.core.summarizer import Reply  # noqa: E402
from newscrawler.web import followup  # noqa: E402
from newscrawler.web.filters import Filters  # noqa: E402
from newscrawler.web.query_processor import passes_floor  # noqa: E402

QA_HELDOUT_B = [  # scripts/experiments/qa_2026_10_13/probe_qa_heldout.py PAIRS
    ("Berapa harga emas Antam hari ini?", "Apa sebaiknya dilakukan investor saham Garuda Indonesia?", ["garuda"]),
    ("Apa kata OJK soal kredit perbankan?", "Bagaimana nantinya nasib karyawan Sritex?", ["sritex"]),
    ("Bagaimana kinerja IHSG hari ini?", "Apa sebetulnya masalah utang Waskita Karya?", ["waskita"]),
    ("Berapa harga emas Antam hari ini?", "Siapa direktur utama Garuda Indonesia dan apa rencananya?", ["garuda"]),
    ("Apa kata OJK soal kredit perbankan?", "Apa itu Danantara dan siapa pemimpinnya?", ["danantara"]),
    ("Bagaimana kasus korupsi timah?", "Bagaimana kinerja saham BBCA dan dividennya?", ["bbca", "bca"]),
    ("Apa kabar program Makan Bergizi Gratis?", "Siapa pengelolanya?", ["mbg", "makan bergizi", "bgn"]),
]
QA_1012B = [  # scripts/experiments/qa_2026_10_12b/probe_qa_followup_pairs.py
    ("Berapa harga emas Antam hari ini?", "Apa yang sebenarnya terjadi pada Garuda Indonesia?", ["garuda"]),
    ("Apa kata OJK soal kredit perbankan?", "Bagaimana nasib Sritex selanjutnya?", ["sritex"]),
    ("Kenapa rupiah melemah pekan ini?", "Apakah Danantara akhirnya membeli saham Garuda?", ["danantara"]),
    ("Apa kabar program Makan Bergizi Gratis?", "Berapa anggarannya tahun depan?", ["mbg", "makan bergizi"]),
    ("Bagaimana kasus korupsi timah?", "Siapa saja tersangkanya?", ["timah"]),
    ("Apa keputusan The Fed terbaru?", "Bagaimana dampaknya ke rupiah?", ["fed"]),
]
OBJECT = [  # written before the first run; on-topic = the thread's subject
    ("Apa keputusan The Fed terbaru?", "Bagaimana dampaknya ke IHSG?", ["fed"]),
    ("Kenapa harga minyak dunia naik?", "Apa pengaruhnya terhadap Pertamina?", ["minyak"]),
    ("Berapa BI-Rate terbaru?", "Bagaimana dampaknya bagi saham BBRI?", ["bi-rate", "bi rate", "suku bunga"]),
    ("Apa isi kebijakan tarif impor Trump?", "Apa dampaknya ke Indonesia?", ["tarif"]),
    ("Bagaimana kasus korupsi timah?", "Berapa kerugiannya bagi PT Timah?", ["korupsi"]),
    ("Kenapa rupiah melemah pekan ini?", "Apa imbasnya pada Garuda Indonesia?", ["rupiah"]),
]
HELDOUT_1018 = [  # written after run 2, before gate_obj2 saw them: switches (1-4, two built to break it) and objects
    ("Apa kata OJK soal kredit perbankan?", "Apa yang terjadi pada Sritex dan bagaimana nasib karyawannya?", ["sritex"]),
    ("Bagaimana kinerja IHSG hari ini?", "Berapa utang Waskita Karya dan kapan jatuh temponya?", ["waskita"]),
    ("Berapa harga emas Antam hari ini?", "Bagaimana kabar terbaru di Danantara dan siapa direkturnya?", ["danantara"]),
    ("Kenapa rupiah melemah pekan ini?", "Siapa pemilik Sritex dan berapa utangnya?", ["sritex"]),
    ("Apa keputusan OPEC terbaru?", "Apa dampaknya untuk Pertamina?", ["opec"]),
    ("Kenapa harga beras naik?", "Bagaimana pengaruhnya ke Bulog?", ["beras"]),
    ("Apa isi aturan baru OJK soal pinjol?", "Apa artinya bagi Kredivo?", ["pinjol", "pinjaman online"]),
    ("Kenapa saham GoTo anjlok?", "Bagaimana reaksinya di Bursa Efek Indonesia?", ["goto"]),
]
HELDOUT_1018B = [  # written after run 3, before gate_ana ran; pair 3 is built to break both gates
    ("Bagaimana harga emas Antam hari ini?", "Bagaimana nasib proyek di IKN dan siapa kontraktornya?", ["ikn", "nusantara"]),
    ("Apa kata OJK soal kredit perbankan?", "Berapa saham yang dibeli Danantara dan berapa nilainya?", ["danantara"]),
    ("Kenapa harga avtur naik?", "Apa kata Garuda soal dampaknya?", ["avtur"]),
    ("Apa keputusan RUPS BBRI terbaru?", "Berapa dividennya untuk pemegang saham?", ["bbri", "bri"]),
    ("Kenapa ekspor batu bara turun?", "Apa dampaknya ke Kalimantan Timur?", ["batu bara"]),
    ("Bagaimana harga minyak dunia terbaru?", "Apa yang terjadi pada Sritex dan kapan putusan pailitnya?", ["sritex"]),
]
SETS = [("qa_heldout_B", QA_HELDOUT_B), ("qa_1012b", QA_1012B), ("object", OBJECT), ("heldout_1018", HELDOUT_1018),
        ("heldout_1018b", HELDOUT_1018B),
        ("dev_switch", SWITCH), ("dev_elliptical", ELLIPTICAL), ("dev_heldout", HELDOUT)]

_OBJ = re.compile(r"\b(?:ke|terhadap|bagi|kepada)\s+((?:\S+\s+){0,2}\S+)", re.IGNORECASE)
# gate_obj2: also "pada/untuk/di/atas", up to 3 words (the one object-set loss of run 1 was "imbasnya pada Garuda")
_OBJ2 = re.compile(r"\b(?:ke|terhadap|bagi|kepada|pada|untuk|di|atas)\s+((?:\S+\s+){0,3}\S+)", re.IGNORECASE)
# The adverb list before ADR-021 (followup._NOT_REFERENCES at 0469fd3): what "before" and the design candidates
# were measured with on 2026-10-19 04:00.
OLD_NOT_REFERENCES = frozenset({
    "hanya", "punya", "tanya", "bertanya",
    "sebenarnya", "sesungguhnya", "selanjutnya", "sebelumnya", "biasanya", "akhirnya", "misalnya",
    "khususnya", "terutamanya", "sepertinya", "tampaknya", "nampaknya", "kelihatannya", "rupanya",
    "agaknya", "seharusnya", "semestinya", "setidaknya", "sekurangnya", "umumnya", "tentunya", "katanya",
})


def _old_refs(q):
    return [m for m in followup._REFERENCE.finditer(q) if m.group(0).lower() not in OLD_NOT_REFERENCES]


def _new_names(q, previous, skip_objects):
    names = story_words.names(q)
    if skip_objects:
        for m in (_OBJ2 if skip_objects == 2 else _OBJ).finditer(q):
            names -= story_words.names("x " + m.group(1))       # "x ": the phrase's first word is no opener
    return names - story_words.vocabulary(" ".join(previous))


def _gate(skip_objects):
    return lambda q, previous: bool(_old_refs(q)) and not _new_names(q, previous, skip_objects)


def _gate_ana(q, previous):
    """gate_obj2, and a new name in an object phrase still counts when a reference word follows it -- an
    -nya anaphor points backward ("terjadi pada Sritex ... karyawannya"). As measured: the LAST reference;
    the shipped rule reads the FIRST (identical on every pair here, which holds one reference each)."""
    refs = _old_refs(q)
    if not refs or _new_names(q, previous, 2):
        return False
    return not story_words.names(q[:refs[-1].start()]) - story_words.vocabulary(" ".join(previous))


def _resolve_by(thread):
    """followup.resolve with `thread(q, previous)` deciding whether a kept / fallback follow-up takes the thread."""
    def resolve(question, previous, rewritten):
        q = question.strip()
        if not previous:
            return followup.alone(q)
        if rewritten is not None:
            if " ".join(rewritten.split()).lower() != " ".join(q.split()).lower():
                return followup.Retrieval(rewritten, (rewritten,), rewritten, followup.LLM)
            if thread(q, previous):
                return followup._with_thread(q, previous, followup.KEPT_THREAD)
            return followup.Retrieval(rewritten, (rewritten,), rewritten, followup.KEPT)
        if thread(q, previous):
            return followup._with_thread(q, previous, followup.FALLBACK_THREAD)
        return followup.Retrieval(q, (q,), q, followup.FALLBACK_OWN)
    return resolve


class _Echo:
    name, priced = "echo", False

    def __init__(self, text):
        self.text = text

    def complete(self, prompt):
        return Reply(self.text, 0, 0)


def _count(qp, follow, history, words, today):
    ranked, counts = qp.candidates(follow, Filters(), today, history)
    cards = [h for h in ranked if passes_floor(h)][:RAG_TOP_K]
    return sum(1 for h in cards if on_topic(h, words)), len(cards), counts["rewrite"]


def main():
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=_Ledger())
    today = date.today()
    shipped = followup.resolve
    variants = [("before", _resolve_by(lambda q, prev: bool(_old_refs(q)))),
                ("gate", _resolve_by(_gate(False))), ("gate_obj", _resolve_by(_gate(True))),
                ("gate_obj2", _resolve_by(_gate(2))), ("gate_ana", _resolve_by(_gate_ana)), ("now", shipped)]
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
                row["alone"] = _count(qp, follow, [], words, today)
                for vname, fn in variants:
                    followup.resolve = fn
                    qp.rewriter = _Echo(follow)
                    row[f"kept_{vname}"] = _count(qp, follow, hist, words, today)
                    qp.rewriter = None
                    row[f"fb_{vname}"] = _count(qp, follow, hist, words, today)
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
