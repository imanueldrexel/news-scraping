"""SYS-150 (#340): the owner's blind A/B of the story arcs, and the numbers that gate them.

For each date: plan the day once (the real summaries), then build the 5-minute edition twice on
that plan -- today's (NEWSLETTER_ARCS off) and the arcs (on) -- so the arc stage is the only
difference. Writes to --out-dir (default digests/preview/arcs):

    <date>-X.md / <date>-Y.md   the two editions, assigned at random (key.json says which is which)
    <date>-X.pdf / <date>-Y.pdf their phone PDFs (what the owner reads)
    key.json                    {date: {"X": "today" | "arcs", "Y": ...}} -- do not open before reading
    handcheck.csv               one row per timeline item an arc used (same_thread: fill in y/n),
                                per prose sentence with a causal word (attributed: fill in y/n) and
                                per arc (reads_as_story: fill in y/n, SYS-160)
    metrics.json                per date and in total: words, top stories, coverage of the day's 6
                                largest, arcs built/fallback, refusals by reason, items per story,
                                no-history stories, LLM calls/tokens/cost, phone-PDF pages and checks,
                                the repetition share between consecutive days, and whether the
                                back-stories read as stories (`style`, SYS-160: `style_metrics`)

With --compare OLD_DIR (an earlier run's out-dir) it also writes, per date, <date>-compare.md/.pdf:
each arc story three times -- this run's arc, OLD_DIR's arc and today's summary, matched by the
story's lead link -- labelled A/B/C at random (compare_key.json says which is which).

--metrics-from DIR computes `style_metrics` on an earlier run's files alone (no LLM, no DB) and
writes DIR/style_metrics.json: the SYS-160 baseline of a run made before these metrics existed.

Read-only: SELECTs, NEWS_L1 through load_index (never saved), no newsletter_digests row, and the
summarizer is metered here and not counted in api_usage_log. It calls the LLM: ~95 summary calls,
2 editor calls and up to 8 arc calls per date (EXPERIMENTS.md has the measured cost).

    venv\\Scripts\\python.exe scripts\\experiments\\replay_story_arcs.py
    venv\\Scripts\\python.exe scripts\\experiments\\replay_story_arcs.py --dates 2026-10-12 --out-dir digests\\preview\\arcs-test
    venv\\Scripts\\python.exe scripts\\experiments\\replay_story_arcs.py --metrics-from digests\\preview\\arcs
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

from newscrawler.core import arc_style, story_words  # noqa: E402
from newscrawler.core import newsletter_copy as copy  # noqa: E402
from newscrawler.core.source_check import dates_in  # noqa: E402
from newscrawler.core.summarizer import SummarizerError  # noqa: E402

logger = logging.getLogger("replay_story_arcs")

DEFAULT_DATES = [date(2026, 10, 8) + timedelta(days=k) for k in range(5)]
CAUSAL = re.compile(r"\b(?:karena|akibat|dipicu|memicu|sehingga|imbas|lantaran)\b", re.IGNORECASE)
ATTRIBUTION = re.compile(r"\b(?:menurut|kata|ujar|sebut|ungkap|jelas|tutur|klaim|mengatakan|menyatakan|menyebut|"
                         r"mengungkapkan|menjelaskan|menilai|menegaskan)\b", re.IGNORECASE)
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


sentences = arc_style.sentences
HANDCHECK_FIELDS = ["date", "kind", "story", "item_date", "outlet", "text", "same_thread", "attributed",
                    "reads_as_story"]


def content(text: str) -> set:
    return set(story_words.content_words(text))


def handcheck_rows(day: date, edition) -> list:
    """The rows a person fills in: every timeline item an arc used, every causal sentence,
    and each arc as a whole (reads_as_story, SYS-160)."""
    rows = []
    blank = {"item_date": "", "outlet": "", "same_thread": "", "attributed": "", "reads_as_story": ""}
    for entry in edition.trace.get("arcs", []):
        arc = entry["arc"]
        if arc is None:
            continue
        rows.append({**blank, "date": day.isoformat(), "kind": "arc", "story": arc.judul, "text": arc.back_story})
        for item in arc.alur_items:
            rows.append({**blank, "date": day.isoformat(), "kind": "alur", "story": arc.judul,
                         "item_date": item.day.isoformat(), "outlet": item.source, "text": item.headline})
        for sentence in sentences(f"{arc.hari_ini} {arc.latar} {arc.agenda}"):
            if CAUSAL.search(sentence):
                rows.append({**blank, "date": day.isoformat(), "kind": "causal", "story": arc.judul, "text": sentence,
                             "attributed": "" if ATTRIBUTION.search(sentence) else "no attribution word"})
    return rows


def back_stories(edition) -> list:
    """The built arcs' back-stories as `style_metrics` reads them: judul, hari_ini, the second
    paragraph as rendered (latar closed by the agenda) and whether the arc chose any `alur`."""
    return [{"judul": e["arc"].judul, "hari_ini": e["arc"].hari_ini, "back": e["arc"].back_story,
             "alur": bool(e["arc"].alur_items)} for e in edition.trace.get("arcs", []) if e["arc"] is not None]


def style_metrics(records: list) -> dict:
    """SYS-160: does the back-story read as a story or as a chronicle (arc_style)? Over the
    records with a back-story: the share of its sentences that are date-led, calendar dates per
    back-story (mean, max, how many hold >= 3), the process non-event verbs used, and the share
    whose first sentence is tied to today (SYS-159's rule; a story without `alur` is exempt)."""
    backs = [r for r in records if r["back"]]
    said = [s for r in backs for s in sentences(r["back"])]
    dates = [len(dates_in(r["back"])) for r in backs]
    tied = [arc_style.tied_to_today(r["back"], r["judul"], r["hari_ini"]) for r in backs if r["alur"]]
    led = sum(arc_style.date_led(s) for s in said)
    return {"back_stories": len(backs), "sentences": len(said), "date_led": led,
            "date_led_share": round(led / len(said), 3) if said else None,
            "dates_mean": round(sum(dates) / len(dates), 2) if dates else None, "dates_max": max(dates, default=None),
            "with_3_dates_or_more": sum(d >= 3 for d in dates),
            "non_events": sum(len(arc_style.non_events(r["back"])) for r in backs),
            "tied_to_today": sum(tied), "tied_checked": len(tied),
            "tied_share": round(sum(tied) / len(tied), 3) if tied else None}


def stories_in(markdown: str) -> list:
    """The top stories of an edition's markdown: judul, lead link and paragraphs (the
    "Diberitakan n portal" line left out)."""
    reported = "**" + copy.REPORTED_BY.split("{")[0]
    section = markdown.split(f"\n## {copy.TOP_STORIES}", 1)[-1].split("\n## ", 1)[0]
    out = []
    for block in section.split("\n### ")[1:]:
        heading, _, body = block.partition("\n")
        match = re.fullmatch(r"\[(.*)\]\((.*)\)", heading.strip())
        judul, link = match.groups() if match else (heading.strip(), "")
        body = "\n".join(line for line in body.split("\n") if not line.startswith(reported))
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        out.append({"judul": judul, "link": link, "paragraphs": paragraphs})
    return out


def back_stories_from_markdown(arcs_md: str, today_md: str, with_alur: set) -> list:
    """`back_stories` read back from a run's files (--metrics-from): a story is an arc unless its
    first paragraph starts with the same story's summary in today's edition (the fallback renders
    the summary as prose); `with_alur` are the arc juduls handcheck.csv lists timeline items for."""
    summaries = {s["link"]: s["paragraphs"][0] for s in stories_in(today_md) if s["paragraphs"]}
    out = []
    for story in stories_in(arcs_md):
        paragraphs = story["paragraphs"]
        if not paragraphs or (story["link"] in summaries and paragraphs[0].startswith(summaries[story["link"]])):
            continue
        out.append({"judul": story["judul"], "hari_ini": paragraphs[0],
                    "back": paragraphs[1] if len(paragraphs) > 1 else "", "alur": story["judul"] in with_alur})
    return out


def run_key(out_dir: str) -> dict:
    with open(os.path.join(out_dir, "key.json"), encoding="utf-8") as f:
        return json.load(f)


def run_edition(out_dir: str, key: dict, day: str, which: str) -> str:
    """An earlier run's edition of `day` ("today" or "arcs"), through its key.json."""
    label = next(label for label, kind in key[day].items() if kind == which)
    with open(os.path.join(out_dir, f"{day}-{label}.md"), encoding="utf-8") as f:
        return f.read()


def metrics_from(out_dir: str) -> dict:
    """SYS-160's metrics on an earlier run's files: its key.json, editions and handcheck.csv."""
    key = run_key(out_dir)
    with open(os.path.join(out_dir, "handcheck.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out, everything = {"dates": {}}, []
    for day in sorted(key):
        with_alur = {r["story"] for r in rows if r["date"] == day and r["kind"] == "alur"}
        records = back_stories_from_markdown(run_edition(out_dir, key, day, "arcs"),
                                             run_edition(out_dir, key, day, "today"), with_alur)
        out["dates"][day] = style_metrics(records)
        everything += records
    out["total"] = style_metrics(everything)
    return out


def compare_markdown(day: date, new_md: str, old_md: str, today_md: str, rng) -> tuple:
    """(markdown, key) of the 3-way blind read: each of this run's arc stories as A/B/C -- the
    new arc, the old run's arc and today's summary of the same story (lead link) -- in random order."""
    old = {s["link"]: s for s in stories_in(old_md)}
    today = {s["link"]: s for s in stories_in(today_md)}
    lines, key = [f"# Bandingkan · {copy.tanggal(day)}", ""], {}
    for story in stories_in(new_md):
        versions = [("baru", story), ("lama", old.get(story["link"])), ("hari_ini", today.get(story["link"]))]
        versions = [(kind, s) for kind, s in versions if s is not None]
        rng.shuffle(versions)
        lines += [f"## {story['judul']}", ""]
        for label, (kind, s) in zip("ABC", versions):
            key.setdefault(story["judul"], {})[label] = kind
            lines += [f"### Versi {label} · {s['judul']}", ""] + [x for p in s["paragraphs"] for x in (p, "")]
    return "\n".join(lines), key


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
    ap.add_argument("--compare", metavar="OLD_DIR", help="an earlier run's out-dir: write the 3-way blind read")
    ap.add_argument("--metrics-from", metavar="DIR", help="only compute the SYS-160 metrics on an earlier run")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.metrics_from:
        style = metrics_from(args.metrics_from)
        with open(os.path.join(args.metrics_from, "style_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(style, f, ensure_ascii=False, indent=1)
        print("STYLE " + json.dumps(style["total"], ensure_ascii=False))
        return 0
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
    old_key = run_key(args.compare) if args.compare else None
    compare_key, all_backs = {}, []
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
        backs = back_stories(arcs)
        all_backs += backs
        if old_key is not None and day.isoformat() in old_key:
            markdown, compare_key[day.isoformat()] = compare_markdown(
                day, arcs.markdown, run_edition(args.compare, old_key, day.isoformat(), "arcs"), today.markdown, rng)
            path = os.path.join(args.out_dir, f"{day.isoformat()}-compare.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(markdown)
            render_edition_pdf(path)
        current = arcs_with_terkait(arcs)
        d_in, d_out = end[1] - start[1], end[2] - start[2]
        metrics["dates"][day.isoformat()] = {
            "today": edition_metrics(plan, today, replay), "arcs": edition_metrics(plan, arcs, replay),
            "calls": {"summaries": after_plan[0] - start[0], "editions": end[0] - after_plan[0]},
            "tokens": {"input": d_in, "output": d_out}, "cost_usd_peak": round(cost_usd(d_in, d_out, True), 4),
            "phone_pdf_pages": pages, "pdf_checks": checks, "style": style_metrics(backs),
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
        "handcheck_rows": len(rows), "style": style_metrics(all_backs),
        "style_refusals": sum(m["arcs"]["arcs"]["refusals"].get("style", 0) for m in metrics["dates"].values())}
    if compare_key:
        with open(os.path.join(args.out_dir, "compare_key.json"), "w", encoding="utf-8") as f:
            json.dump(compare_key, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out_dir, "key.json"), "w", encoding="utf-8") as f:
        json.dump(key, f, indent=1)
    with open(os.path.join(args.out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(args.out_dir, "handcheck.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HANDCHECK_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("ARCS " + json.dumps(metrics["total"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
