"""SYS-200 (#430) pilot, owner 2026-11-11: the natural set on the `nli_shadow` rows stored so far.

Every row is a published arc sentence with the ids of the quotes the gates read (`premise_ids`). Steps:

  export   nli_shadow + each quote's text -> tests/fixtures/nli_eval/natural_rows.jsonl (read-only on the DB).
           A quote is rebuilt as the arc writer built it: an article of the edition's own date is a `terkait`
           article (`story_summary.guard_text`: headline + l1_text[:ARTICLE_CHARS]); an older one is an `alur` item
           (`story_arc.item_source`: headline + `thread_finder.opening`).
  gemini   gemini-2.5-flash labels each sentence supported / unsupported by its quotes, blind (ADR-026/027), one story
           per call -> natural_gemini_blind.csv. Rows already labelled are skipped (resumes after a 429).
  rescore  --model <name or dir>: best_verdict over the rebuilt quotes, as the shadow scores -> a {id: p_entail} JSON.
  report   labeller agreement (Claude: natural_claude.csv, labelled in session), the unsupported share, gate family
           vs residual, and each scored arm's p_entail by label.
  final    the natural set in eval_nli.py's format -> natural.jsonl. Label precedence (ADR-027): owner ruling
           (natural_owner_rulings.csv) > Claude and Gemini agreeing; a disagreement without a ruling is left out.
           error_type is the row's gate family, or "residual"; kind "natural".

  venv\\Scripts\\python.exe scripts/experiments/nli_natural_pilot.py export
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
FIX = os.path.join(REPO, "tests", "fixtures", "nli_eval")
ROWS = os.path.join(FIX, "natural_rows.jsonl")
CLAUDE = os.path.join(FIX, "natural_claude.csv")
GEMINI = os.path.join(FIX, "natural_gemini_blind.csv")
RULINGS = os.path.join(FIX, "natural_owner_rulings.csv")
NATURAL = os.path.join(FIX, "natural.jsonl")
LABELS = ("supported", "unsupported")
FIELDS = ["id", "label", "reason"]

PROMPT = """You check sentences of an Indonesian news newsletter against their sources. For each SENTENCE, decide
whether the SOURCES of its story, taken together, support everything it states:
- "supported": every fact in the sentence (who, what, numbers, dates, causes, whether something is certain, denied
  or only planned) is stated by the sources, or follows from them directly; rewording and shortening are fine;
- "unsupported": the sentence states something the sources do not: a fact, number or date they lack, a cause they
  do not give, a certainty where they hedge, a denial turned into an admission, or the reverse.
Judge only against the sources below, not against what you know.

SOURCES:
{sources}

SENTENCES (JSON):
{sentences}

Reply as JSON only: {{"labels": [{{"id": "...", "label": "supported"|"unsupported", "reason": "one short sentence"}}]}}
with exactly one entry per sentence id."""


def _connect():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    import psycopg2
    c = psycopg2.connect(host=os.getenv("POSTGRES_DB_HOST", "localhost"), port=os.getenv("POSTGRES_DB_PORT", "5431"),
                         dbname=os.getenv("POSTGRES_DB_NAME", "newsaggregator"), user=os.getenv("POSTGRES_DB_USER"),
                         password=os.getenv("POSTGRES_DB_PASS"))
    c.set_session(readonly=True)
    return c


def quote_text(row: dict, edition_int: int) -> (str, str):
    """(role, text) of one quote, rebuilt as the arc writer read it."""
    from newscrawler.core.story_summary import guard_text
    from newscrawler.core.thread_finder import opening
    if row["posted_at"] == edition_int:
        return "terkait", guard_text({"headline": row["headline"], "l1_text": row["l1_text"]})
    return "alur", f"{row['headline']}\n{opening(row['l1_text'])}"


def export(out: str) -> int:
    from newscrawler.core.utils.utils import unescape_headline
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT shadow_id, edition_date, story_id, field, sentence, error_tags, premise_ids, p_entail, "
                "model_revision FROM nli_shadow ORDER BY edition_date, story_id, shadow_id")
    shadow = cur.fetchall()
    ids = sorted({int(i) for r in shadow for i in (r[6] or [])})
    cur.execute("SELECT s.sitemap_id, s.headline, s.posted_at, c.text_content FROM sitemaps s "
                "LEFT JOIN chunks c ON c.sitemap_id = s.sitemap_id AND c.chunk_level = 1 "
                "WHERE s.sitemap_id = ANY(%s)", (ids,))
    texts = {r[0]: {"headline": unescape_headline(r[1] or ""), "posted_at": r[2], "l1_text": r[3] or ""}
             for r in cur.fetchall()}
    missing = 0
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for sid, day, story, field, sentence, tags, premise_ids, p_entail, revision in shadow:
            edition_int = int(day.strftime("%Y%m%d"))
            quotes = []
            for pid in premise_ids or []:
                if pid not in texts:
                    missing += 1
                    continue
                role, text = quote_text(texts[pid], edition_int)
                quotes.append({"sitemap_id": pid, "role": role, "text": text})
            f.write(json.dumps({"id": f"n{sid}", "edition_date": day.isoformat(), "story": f"{day.isoformat()}#{story}",
                                "field": field, "sentence": sentence, "error_tags": tags, "quotes": quotes,
                                "stored_p_entail": p_entail, "stored_revision": revision},
                               ensure_ascii=False) + "\n")
    print(f"{len(shadow)} sentences, {len(texts)} quotes, {missing} quote ids without a sitemap -> {out}")
    return 0


def read_rows(path: str = ROWS) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_labels(path: str) -> Dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def write_labels(path: str, labels: Dict[str, dict], order: List[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(labels[i] for i in order if i in labels)


def by_story(rows: List[dict]) -> Dict[str, List[dict]]:
    out = defaultdict(list)
    for r in rows:
        out[r["story"]].append(r)
    return dict(out)


def story_prompt(story_rows: List[dict]) -> str:
    quotes = {q["sitemap_id"]: q["text"] for r in story_rows for q in r["quotes"]}
    sources = "\n\n".join(f"[{i}] {t}" for i, t in quotes.items())
    sentences = [{"id": r["id"], "sentence": r["sentence"]} for r in story_rows]
    return PROMPT.format(sources=sources, sentences=json.dumps(sentences, ensure_ascii=False, indent=1))


def parse(text: str, story_rows: List[dict]) -> Dict[str, dict]:
    from newscrawler.core.llm_json import json_object
    got = {}
    for lab in json_object(text).get("labels", []):
        label = str(lab.get("label", "")).strip().lower()
        if label not in LABELS:
            raise ValueError(f"bad label {lab!r}")
        got[str(lab["id"])] = {"id": str(lab["id"]), "label": label, "reason": str(lab.get("reason", ""))}
    want = {r["id"] for r in story_rows}
    if set(got) != want:
        raise ValueError(f"ids differ: missing {sorted(want - set(got))}, extra {sorted(set(got) - want)}")
    return got


def gemini(out: str) -> int:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    from newscrawler.core.extraction_provider import ProviderTransientError, build_provider
    provider = build_provider("gemini")
    if provider is None:
        print("GEMINI_API_KEY is not set")
        return 1
    rows = read_rows()
    have = read_labels(out)
    calls = 0
    for story, story_rows in by_story(rows).items():
        if all(r["id"] in have for r in story_rows):
            continue
        try:
            completion = provider.complete(story_prompt(story_rows))
        except ProviderTransientError as e:
            print(f"stopped after {calls} calls: {type(e).__name__}: {str(e)[:160]}")
            write_labels(out, have, [r["id"] for r in rows])
            return 1
        calls += 1
        have.update(parse(completion.text, story_rows))
        write_labels(out, have, [r["id"] for r in rows])
    print(f"{provider.name}: {calls} calls, {len(have)}/{len(rows)} labelled -> {out}")
    return 0


def rescore(model: str, out: str) -> int:
    from newscrawler.core.nli_check import HfScorer, best_verdict
    scorer = HfScorer(model)
    scores = {}
    for r in read_rows():
        verdict = best_verdict(scorer, [q["text"] for q in r["quotes"]], r["sentence"])
        scores[r["id"]] = None if verdict is None else verdict.p_entail
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": scorer.revision, "scores": scores}, f, indent=1)
    print(f"{scorer.revision}: {sum(v is not None for v in scores.values())}/{len(scores)} scored -> {out}")
    return 0


def report(score_files: List[str]) -> int:
    rows = read_rows()
    claude, gem = read_labels(CLAUDE), read_labels(GEMINI)
    both = [r["id"] for r in rows if r["id"] in claude and r["id"] in gem]
    agree = [i for i in both if claude[i]["label"] == gem[i]["label"]]
    print(f"rows {len(rows)}; labelled by both {len(both)}; agree {len(agree)}/{len(both)}")
    for i in both:
        if claude[i]["label"] != gem[i]["label"]:
            print(f"  DISAGREE {i}: claude={claude[i]['label']} gemini={gem[i]['label']} | {gem[i]['reason']}")
    final = {i: claude[i]["label"] for i in agree}
    print(f"unsupported (both agree): {sum(v == 'unsupported' for v in final.values())}/{len(final)}")
    family = Counter((r["error_tags"] or "residual") for r in rows)
    print("gate families:", dict(family))
    for path in score_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        scores = data["scores"]
        print(f"--- {data['model']}")
        for label in LABELS:
            vals = sorted(scores[i] for i, v in final.items() if v == label and scores.get(i) is not None)
            if vals:
                lows = {t: sum(v < t for v in vals) for t in (0.1, 0.3, 0.5)}
                print(f"  {label:11s} n={len(vals):3d} min={vals[0]:.3f} median={vals[len(vals) // 2]:.3f} "
                      f"below 0.1/0.3/0.5: {lows[0.1]}/{lows[0.3]}/{lows[0.5]}")
    return 0


def final_labels(rows: List[dict]) -> Dict[str, str]:
    """{id: supported|unsupported}: an owner ruling first, else the two labellers agreeing."""
    claude, gem, rulings = read_labels(CLAUDE), read_labels(GEMINI), read_labels(RULINGS)
    out = {}
    for r in rows:
        i = r["id"]
        if i in rulings:
            out[i] = rulings[i]["label"]
        elif i in claude and i in gem and claude[i]["label"] == gem[i]["label"]:
            out[i] = claude[i]["label"]
    return out


def final(out: str) -> int:
    rows = read_rows()
    labels = final_labels(rows)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            if r["id"] not in labels:
                continue
            f.write(json.dumps({"id": r["id"], "error_type": r["error_tags"] or "residual",
                                "premise": "\n\n".join(q["text"] for q in r["quotes"]), "hypothesis": r["sentence"],
                                "label": "unfaithful" if labels[r["id"]] == "unsupported" else "faithful",
                                "kind": "natural"}, ensure_ascii=False) + "\n")
    counts = Counter(labels.values())
    print(f"{len(labels)}/{len(rows)} rows ({dict(counts)}) -> {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export").add_argument("--out", default=ROWS)
    sub.add_parser("gemini").add_argument("--out", default=GEMINI)
    r = sub.add_parser("rescore")
    r.add_argument("--model", required=True)
    r.add_argument("--out", required=True)
    sub.add_parser("report").add_argument("--scores", nargs="*", default=[])
    sub.add_parser("final").add_argument("--out", default=NATURAL)
    args = ap.parse_args(argv)
    if args.cmd == "final":
        return final(args.out)
    if args.cmd == "export":
        return export(args.out)
    if args.cmd == "gemini":
        return gemini(args.out)
    if args.cmd == "rescore":
        return rescore(args.model, args.out)
    return report(args.scores)


if __name__ == "__main__":
    sys.exit(main())
