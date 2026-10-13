"""SYS-150 (#340): the owner's blind A/B of the story arcs, and the numbers that gate them.

For each date: plan the day once (the real summaries), then build the 5-minute edition twice on
that plan -- today's (NEWSLETTER_ARCS off) and the arcs (on) -- so the arc stage is the only
difference. Writes to --out-dir (default digests/preview/arcs):

    <date>-X.md / <date>-Y.md   the two editions, assigned at random (key.json says which is which)
    <date>-X.pdf / <date>-Y.pdf their phone PDFs (what the owner reads)
    key.json                    {date: {"X": "today" | "arcs", "Y": ...}} -- do not open before reading
    handcheck.csv               one row per timeline item an arc used (same_thread: fill in y/n)
                                and per prose sentence with a causal word (attributed: fill in y/n)
    metrics.json                per date and in total: words, top stories, coverage of the day's 6
                                largest, arcs built/fallback, refusals by reason, items per story,
                                no-history stories, LLM calls/tokens/cost, phone-PDF pages and checks,
                                and the repetition share between consecutive days

Read-only: SELECTs, NEWS_L1 through load_index (never saved), no newsletter_digests row, and the
summarizer is metered here and not counted in api_usage_log. It calls the LLM: ~95 summary calls,
2 editor calls and up to 8 arc calls per date (EXPERIMENTS.md has the measured cost).

    venv\\Scripts\\python.exe scripts\\experiments\\replay_story_arcs.py
    venv\\Scripts\\python.exe scripts\\experiments\\replay_story_arcs.py --dates 2026-10-12 --out-dir digests\\preview\\arcs-test
"""
import argparse
import csv
import json
import logging
import os
import random
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experiments"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from newscrawler.core import story_words  # noqa: E402
from newscrawler.core.summarizer import SummarizerError  # noqa: E402

logger = logging.getLogger("replay_story_arcs")

DEFAULT_DATES = [date(2026, 10, 8) + timedelta(days=k) for k in range(5)]
CAUSAL = re.compile(r"\b(?:karena|akibat|dipicu|memicu|sehingga|imbas|lantaran)\b", re.IGNORECASE)
ATTRIBUTION = re.compile(r"\b(?:menurut|kata|ujar|sebut|ungkap|jelas|tutur|klaim)\b", re.IGNORECASE)
REPEAT_SHARE = 0.6        # a latar sentence repeats yesterday's when it shares this share of its content words


class Metered:
    """The configured summarizer, its calls and tokens counted here (not in api_usage_log)."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name
        self.calls = self.input_tokens = self.output_tokens = 0

    def summarize(self, prompt: str) -> str:
        reply = self.inner.complete(prompt)
        self.calls += 1
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        text = (reply.text or "").strip()
        if not text:
            raise SummarizerError("empty answer")
        return text

    def snapshot(self):
        return (self.calls, self.input_tokens, self.output_tokens)


def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def content(text: str) -> set:
    return set(story_words.content_words(text))


def handcheck_rows(day: date, edition) -> list:
    """The rows a person fills in: every timeline item an arc used, every causal sentence."""
    rows = []
    for entry in edition.trace.get("arcs", []):
        arc = entry["arc"]
        if arc is None:
            continue
        for item in arc.alur_items:
            rows.append({"date": day.isoformat(), "kind": "alur", "story": arc.judul, "item_date": item.day.isoformat(),
                         "outlet": item.source, "text": item.headline, "same_thread": "", "attributed": ""})
        for sentence in sentences(f"{arc.hari_ini} {arc.latar} {arc.agenda}"):
            if CAUSAL.search(sentence):
                rows.append({"date": day.isoformat(), "kind": "causal", "story": arc.judul, "item_date": "",
                             "outlet": "", "text": sentence, "same_thread": "",
                             "attributed": "" if ATTRIBUTION.search(sentence) else "no attribution word"})
    return rows


def repetition(today_arcs: list, yesterday_arcs: list) -> dict:
    """Of today's latar sentences in a story that continues one of yesterday's (today's timeline
    holds an article of yesterday's story), how many share >= REPEAT_SHARE of their content words
    with a latar sentence of that story yesterday."""
    total = repeated = 0
    for arc, terkait in today_arcs:
        if arc is None:
            continue
        used = {t.sitemap_id for t in arc.alur_items}
        matches = [y for y, y_terkait in yesterday_arcs if y is not None and used & set(y_terkait)]
        old = [content(s) for y in matches for s in sentences(y.latar)]
        for sentence in sentences(arc.latar):
            words = content(sentence)
            if not words or not old:
                continue
            total += 1
            repeated += any(len(words & o) / len(words) >= REPEAT_SHARE for o in old)
    return {"sentences": total, "repeated": repeated, "share": round(repeated / total, 3) if total else None}


def arcs_with_terkait(edition) -> list:
    stories = {s["judul"]: s["terkait_ids"] for s in (edition.stories or [])}
    return [(e["arc"], stories.get(e["arc"].judul, []) if e["arc"] else []) for e in edition.trace.get("arcs", [])]


def edition_metrics(plan, edition, replay) -> dict:
    out = {"words": edition.words, "utama": edition.utama, "sekilas": edition.sekilas,
           "editor_fallback": edition.editor_fallback, "coverage": replay.coverage(plan, edition)}
    if edition.arcs is not None:
        items = [len(e["arc"].alur_items) for e in edition.trace["arcs"] if e["arc"]]
        out["arcs"] = edition.arcs
        out["items_per_story"] = items
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dates", nargs="*", help="YYYY-MM-DD ... (default 2026-10-08..2026-10-12)")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "digests", "preview", "arcs"))
    ap.add_argument("--seed", type=int, default=None, help="the X/Y assignment's seed (default: random)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    days = [date.fromisoformat(d) for d in args.dates] if args.dates else DEFAULT_DATES
    os.makedirs(args.out_dir, exist_ok=True)

    import replay_newsletter_edition as replay
    from newscrawler.application.newsletter_app import build_newsletter_service
    from newscrawler.core.newsletter_pdf import render_edition_pdf
    from newscrawler.core.peak_hours import cost_usd
    from newscrawler.core.summarizer import build_summarizer
    from pypdf import PdfReader

    inner = build_summarizer(usage=None)
    if inner is None:
        logger.error("no summarizer configured (OPENAI_API_KEY / GEMINI_API_KEY): nothing to replay")
        return 1
    meter = Metered(inner)
    generator = build_newsletter_service(summarizer=meter).generator
    rng = random.Random(args.seed)
    key, metrics, rows, previous = {}, {"dates": {}}, [], None
    for day in days:
        start = meter.snapshot()
        plan = generator.plan(day)
        if plan is None:
            logger.warning(f"{day}: no articles")
            continue
        after_plan = meter.snapshot()
        today = generator.build_edition(plan, arcs=False)
        arcs = generator.build_edition(plan, arcs=True)
        end = meter.snapshot()
        labels = ["X", "Y"]
        rng.shuffle(labels)
        key[day.isoformat()] = {labels[0]: "today", labels[1]: "arcs"}
        pages, checks = {}, {}
        for label, edition in zip(labels, (today, arcs)):
            path = os.path.join(args.out_dir, f"{day.isoformat()}-{label}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(edition.markdown)
            pdf = render_edition_pdf(path)
            pages[label] = len(PdfReader(pdf).pages)
            checks[label] = replay.document_checks([path], [pdf])
        rows += handcheck_rows(day, arcs)
        current = arcs_with_terkait(arcs)
        d_in, d_out = end[1] - start[1], end[2] - start[2]
        metrics["dates"][day.isoformat()] = {
            "today": edition_metrics(plan, today, replay), "arcs": edition_metrics(plan, arcs, replay),
            "calls": {"summaries": after_plan[0] - start[0], "editions": end[0] - after_plan[0]},
            "tokens": {"input": d_in, "output": d_out}, "cost_usd_peak": round(cost_usd(d_in, d_out, True), 4),
            "phone_pdf_pages": pages, "pdf_checks": checks,
            "repetition_vs_previous_day": repetition(current, previous) if previous is not None else None}
        previous = current
        logger.info(f"{day}: today {today.words} words / {today.utama} top; arcs {arcs.words} words / "
                    f"{arcs.utama} top, {arcs.arcs}")
    reps = [m["repetition_vs_previous_day"] for m in metrics["dates"].values() if m["repetition_vs_previous_day"]]
    total_sentences = sum(r["sentences"] for r in reps)
    metrics["total"] = {
        "cost_usd_peak": round(sum(m["cost_usd_peak"] for m in metrics["dates"].values()), 4),
        "arcs_built": sum(m["arcs"]["arcs"]["built"] for m in metrics["dates"].values()),
        "arcs_fallback": sum(m["arcs"]["arcs"]["fallback"] for m in metrics["dates"].values()),
        "max_words_arcs": max((m["arcs"]["words"] for m in metrics["dates"].values()), default=None),
        "repetition_share": round(sum(r["repeated"] for r in reps) / total_sentences, 3) if total_sentences else None,
        "handcheck_rows": len(rows)}
    with open(os.path.join(args.out_dir, "key.json"), "w", encoding="utf-8") as f:
        json.dump(key, f, indent=1)
    with open(os.path.join(args.out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(args.out_dir, "handcheck.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "kind", "story", "item_date", "outlet", "text", "same_thread",
                                               "attributed"])
        writer.writeheader()
        writer.writerows(rows)
    print("ARCS " + json.dumps(metrics["total"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
