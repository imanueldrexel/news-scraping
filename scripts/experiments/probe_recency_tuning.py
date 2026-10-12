"""SYS-138 / SYS-112 (ADR-012): tune how a question's recency cue weighs, offline.

Step 1, `--dump PATH` (read-only, loads MiniLM + FAISS, ~1 min): for every question below, the
current code's candidates unfiltered and with a 7-day window (Filters(days=7)), each with its
signals (semantic, keyword coverage, date, origin, title), to a JSON file.

Step 2, `--eval PATH` (no I/O but the file): re-rank the dumped candidates under each parameter
setting in GRID and print, per setting, the targets' metrics:
  - SYS-138: the week questions, cards posted within the last 7 days of `today` (>= 3 of 5);
  - SYS-112: the "sekarang"/"terbaru" questions, on-topic cards in the top 3 (title words);
  - regression: every other question's on-topic cards in the top 5, against the current setting.
"On topic" is a title holding one of the question's subject words: a check on the hand reading.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_recency_tuning.py --dump recency_dump.json
    venv\\Scripts\\python.exe scripts\\experiments\\probe_recency_tuning.py --eval recency_dump.json
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# (question, subject words in a relevant title, role)
QUESTIONS = [
    ("Apa perkembangan kasus korupsi yang ditangani KPK minggu ini?", ["kpk"], "week"),
    ("Bagaimana kinerja IHSG pekan ini?", ["ihsg"], "week"),
    ("Kenapa rupiah melemah pekan ini?", ["rupiah"], "week"),
    ("Di mana terjadi banjir atau longsor dalam sepekan terakhir?", ["banjir", "longsor"], "week"),
    ("Siapa Menteri Keuangan sekarang?", ["menkeu", "menteri keuangan", "wamenkeu", "suahasil"], "now"),
    ("Apa keputusan BI terbaru soal suku bunga?", ["bi rate", "bi-rate", "suku bunga acuan", "tahan suku bunga",
                                                   "pangkas suku bunga", "turunkan suku bunga"], "now"),
    ("Berapa harga emas Antam hari ini?", ["antam"], "now"),
    ("Apa keputusan Bank Indonesia soal suku bunga terbaru?", ["bi rate", "bi-rate", "suku bunga acuan",
                                                               "tahan suku bunga", "pangkas suku bunga"], "now"),
    ("Bagaimana harga minyak dunia terbaru?", ["minyak"], "now"),
    ("Bagaimana perkembangan konflik Iran terbaru?", ["iran"], "now"),
    ("Apa keputusan Bank Indonesia soal BI-Rate?", ["bi rate", "bi-rate", "suku bunga"], "plain"),
    ("Apa kata OJK soal kredit perbankan?", ["ojk", "kredit"], "plain"),
    ("Apa isi RUU Ketenagakerjaan yang baru disahkan?", ["ketenagakerjaan", "buruh", "pekerja"], "plain"),
    ("Apa itu Danantara?", ["danantara"], "plain"),
    ("qwerty asdf zxcv", [], "none"),
]

# (name, {cue horizon days: soft window days}, relative gate delta or None). The cue horizons are
# keywords.recency_cue's: 1 = "hari ini/sekarang", 3 = "pekan/minggu ini", 7 = "terbaru".
GRID = [
    ("current", {}, None),
    ("week7", {3: 7}, None),
    ("gate0.10", {}, 0.10),
    ("gate0.15", {}, 0.15),
    ("week7+gate0.10", {3: 7}, 0.10),
    ("week7+gate0.15", {3: 7}, 0.15),
    ("week7+now7", {3: 7, 1: 7}, None),
    ("week7+now7+gate0.10", {3: 7, 1: 7}, 0.10),
    ("week7+now7+gate0.15", {3: 7, 1: 7}, 0.15),
    ("week7+now3", {3: 7, 1: 3}, None),
    ("week7+now3+gate0.10", {3: 7, 1: 3}, 0.10),
    ("week7+now3+gate0.15", {3: 7, 1: 3}, 0.15),
]


def dump(path):
    import probe_rag_rank_breakdown as p  # noqa: F401 -- loads .env, puts the repo on sys.path
    from newscrawler.web.filters import Filters
    qp = p.QueryProcessor(p.ChunkFAISSDatasource(), p.SQLAlchemyClient(), summarizer=None, usage=None,
                          rewriter=None)
    today = date.today()
    out = {"today": today.isoformat(), "questions": []}

    def signals(hits):
        return [{"sitemap_id": h.get("sitemap_id"), "semantic": h.get("semantic_score", 0.0),
                 "keyword": h.get("keyword_score", 0.0), "posted_at": str(h.get("posted_at") or ""),
                 "origin": h.get("origin"), "title": h.get("title") or "",
                 "words": len((h.get("text_content") or "").split())} for h in hits]
    for q, words, role in QUESTIONS:
        full, counts = qp.candidates(q, Filters(), today)
        window, _ = qp.candidates(q, Filters(days=7), today)
        out["questions"].append({"q": q, "words": words, "role": role, "cue": counts["recent"],
                                 "full": signals(full), "window": signals(window)})
        print(f"{q[:60]:60} full={len(full)} window={len(window)} cue={counts['recent']}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)


def _rank(cands, today, cue, delta):
    from newscrawler.core.constants import RAG_BM25_WEIGHT, RAG_MIN_SEMANTIC_SCORE, RAG_RECENCY_WEIGHT, \
        RAG_SEMANTIC_WEIGHT
    from newscrawler.web.query_processor import posted_date, recency
    best = max((c["semantic"] for c in cands), default=0.0)
    ranked = []
    for c in cands:
        d = posted_date(c["posted_at"])
        if cue is None:
            fresh = recency(d, today) * RAG_RECENCY_WEIGHT
        else:
            relevant = c["semantic"] >= RAG_MIN_SEMANTIC_SCORE and (delta is None or c["semantic"] >= best - delta)
            fresh = recency(d, today, cue[0]) * cue[1] if relevant else 0.0
        ranked.append((c["semantic"] * RAG_SEMANTIC_WEIGHT + c["keyword"] * RAG_BM25_WEIGHT + fresh, c))
    return [c for _, c in sorted(ranked, key=lambda x: x[0], reverse=True)]


def _cards(question, today, windows, delta):
    from newscrawler.core.constants import RAG_TOP_K
    from newscrawler.web import keywords
    from newscrawler.web.query_processor import passes_floor

    def floor(c):
        return passes_floor({"semantic_score": c["semantic"], "keyword_score": c["keyword"]})
    cue_obj = keywords.recency_cue(question["q"])
    cue = (cue_obj.days, cue_obj.weight) if cue_obj else None
    full = [c for c in _rank(question["full"], today, cue, delta) if floor(c)]
    window_days = windows.get(cue[0]) if cue else None
    if window_days:
        # The dump's window set is the 7-day retrieval; a shorter window is its subset by date.
        first = int((today - timedelta(days=window_days - 1)).strftime("%Y%m%d"))
        inside = [c for c in question["window"] if c["posted_at"][:8].isdigit() and int(c["posted_at"][:8]) >= first]
        win = [c for c in _rank(inside, today, cue, delta) if floor(c)]
        if len(win) >= RAG_TOP_K:
            return win[:RAG_TOP_K]
        seen = {c["sitemap_id"] for c in win}
        return (win + [c for c in full if c["sitemap_id"] not in seen])[:RAG_TOP_K]
    return full[:RAG_TOP_K]


def evaluate(path):
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    today = date.fromisoformat(data["today"])
    week_start = int((today - timedelta(days=6)).strftime("%Y%m%d"))

    def on_topic(c, words):
        t = c["title"].lower()
        return any(w in t for w in words)
    baseline = {}
    for name, windows, delta in GRID:
        print(f"\n######## {name}")
        lines, score = [], {"week>=3": 0, "now_top3": 0, "regress": 0}
        for question in data["questions"]:
            cards = _cards(question, today, windows, delta)
            ids = [c["sitemap_id"] for c in cards]
            topical = sum(1 for c in cards if on_topic(c, question["words"]))
            recent = sum(1 for c in cards if c["posted_at"][:8].isdigit() and int(c["posted_at"][:8]) >= week_start)
            top3 = sum(1 for c in cards[:3] if on_topic(c, question["words"]))
            if name == "current":
                baseline[question["q"]] = (ids, topical)
            base_ids, base_topical = baseline[question["q"]]
            note = ""
            if question["role"] == "week":
                score["week>=3"] += recent >= 3
                note = f"week {recent}/5"
            elif question["role"] == "now":
                score["now_top3"] += top3
                note = f"top3 {top3}/3"
            if topical < base_topical:
                score["regress"] += 1
                note += f"  REGRESSION {base_topical}->{topical}"
            dates = ",".join(c["posted_at"][4:8] for c in cards)
            lines.append(f"  {question['q'][:52]:52} on-topic {topical}/{len(cards)} {note:24} dates={dates}")
        print("\n".join(lines))
        print(f"  == {score}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump")
    ap.add_argument("--eval")
    args = ap.parse_args()
    if args.dump:
        dump(args.dump)
    if args.eval:
        evaluate(args.eval)
