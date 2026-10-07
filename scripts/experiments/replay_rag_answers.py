"""SYS-99 (#268) / SYS-98 (#267) replay: ask the running search app real questions and check
each answer against the ticket's rules, for a hand check.

It talks to the app's JSON API (`POST /api/query`), so it loads no model of its own and
measures the real path: retrieval on production, the answer from RAG_LLM_PROVIDER. Each
question is one paid call (~$0.001 on DeepSeek), counted under `web:<model>`.

Checks per answer (automatic; the hand check reads the dump):
- every [n] names a returned source (1..len(sources));
- <= 120 words without the citations;
- no Markdown symbols, no English month, no internal source name, no 8-digit date;
- the not-enough sentence is the exact one when the model uses it;
- the number check's flag.

    venv\\Scripts\\python.exe scripts\\experiments\\replay_rag_answers.py --base http://127.0.0.1:8765 --out <dir>
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from newscrawler.core import web_copy  # noqa: E402
from newscrawler.core.newsletter_copy import OUTLET_NAMES  # noqa: E402

QUESTIONS = [
    {"query": "Kenapa rupiah melemah pekan ini?"},
    {"query": "Bagaimana kinerja IHSG pekan ini?", "topic": "markets", "rentang": "7"},
    {"query": "Apa kata OJK soal kredit perbankan?"},
    {"query": "Apa isi RUU Ketenagakerjaan yang baru disahkan?"},
    {"query": "Bagaimana harga minyak dunia terbaru?", "topic": "commodities_energy"},
    {"query": "Apa perkembangan kasus korupsi yang ditangani KPK minggu ini?", "rentang": "7"},
    {"query": "Di mana terjadi banjir atau longsor dalam sepekan terakhir?", "topic": "disaster_accident", "rentang": "7"},
    {"query": "Apa keputusan Bank Indonesia soal suku bunga terbaru?", "followup": "Apa dampaknya ke kredit perbankan?"},
    {"query": "Bagaimana perkembangan konflik Iran terbaru?", "topic": "international"},
    {"query": "Apa keputusan Bank Indonesia soal BI-Rate?"},     # SYS-103's Done-when: the decision in the top 5
]
# Only spellings Indonesian does not share (April, September, November, Jan, Feb, ... are both).
ENGLISH_MONTHS = r"\b(January|February|March|May|June|July|August|October|December|Aug|Oct|Dec)\b"
CITE = re.compile(r"\[(\s*\d+\s*(?:[,;–—-]\s*\d+\s*)*)\]")


def post(base, payload):
    req = urllib.request.Request(f"{base}/api/query", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    body["_seconds"] = round(time.monotonic() - start, 1)
    return body


def check(result):
    answer, n_sources = result.get("answer", ""), len(result.get("sources", []))
    problems = []
    numbers = [int(x) for m in CITE.finditer(answer) for x in re.findall(r"\d+", m.group(1))]
    if any(not 1 <= n <= n_sources for n in numbers):
        problems.append(f"citation out of range {numbers} / {n_sources}")
    words = len(CITE.sub("", answer).split())
    if words > 120:
        problems.append(f"{words} words")
    if re.search(r"\*\*|__|^#|`", answer, re.M):
        problems.append("markdown")
    if re.search(ENGLISH_MONTHS, answer):
        problems.append("english month")
    bare = answer
    for brand in sorted(OUTLET_NAMES.values(), key=len, reverse=True):
        bare = bare.replace(brand, " ")
    leaked = [s for s in OUTLET_NAMES if re.search(rf"\b{s}\b", bare)]
    if leaked:
        problems.append(f"internal names {leaked}")
    if re.search(r"\b20\d{6}\b", answer):
        problems.append("yyyymmdd date")
    if re.search(r"konteks|sebagai AI|artikel yang diberikan", answer, re.I):
        problems.append("forbidden phrase")
    if "belum cukup" in answer and web_copy.NOT_ENOUGH not in answer:
        problems.append("not-enough sentence reworded")
    return {"words": words, "citations": sorted(set(numbers)), "problems": problems}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rows = []
    for q in QUESTIONS:
        payload = {k: v for k, v in q.items() if k != "followup"}
        result = post(args.base, payload)
        rows.append({"request": payload, "result": result, "check": check(result)})
        if q.get("followup"):
            follow = {"query": q["followup"], "session_id": result["session_id"]}
            result2 = post(args.base, follow)
            rows.append({"request": follow, "result": result2, "check": check(result2)})
    with open(os.path.join(args.out, "replay.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    md = []
    for i, row in enumerate(rows, 1):
        r, c = row["result"], row["check"]
        md.append(f"## {i}. {row['request']['query']}  ({', '.join(f'{k}={v}' for k, v in row['request'].items() if k not in ('query', 'session_id')) or 'no filter'})")
        md.append(f"status={r['answer_status']} · {r['_seconds']} s · {c['words']} words · cites {c['citations']} · "
                  f"unverified={r['numbers_unverified']} · problems={c['problems'] or 'none'}\n")
        md.append(r.get("answer") or "(no answer)")
        md.append("")
        for s in r.get("sources", []):
            md.append(f"- [{s['n']}] {s['outlet']} · {s['date']} · {s['topic_name']} · {s['title']}")
        md.append("")
    with open(os.path.join(args.out, "replay.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    ok = sum(1 for row in rows if row["result"]["answer_status"] == "ok")
    clean = sum(1 for row in rows if not row["check"]["problems"])
    print(f"{len(rows)} questions: {ok} answered, {clean} with no automatic problem; "
          f"{sum(r['result']['numbers_unverified'] for r in rows)} flagged numbers. See {args.out}/replay.md")


if __name__ == "__main__":
    main()
