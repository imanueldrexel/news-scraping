#!/usr/bin/env python3
"""
OPS-18 (#123): a weekly, independent audit of the news-worthy filter.

Every filter regression so far (SYS-31, SYS-34, SYS-35) was found by a QA audit
weeks after it started. This samples the last week's probe decisions -- up to
100 saved and 100 `rejected_filter` rows, spread across sources -- and asks the
labeller that built the SYS-36 gold set to judge them with the same rubric and
prompt (`filter_rubric.build_label_prompt`, `label_filter_gold.parse_labels`).
The LLM judges a sample; it never gates an article.

Excluded from the sample: rejects the category deny-list made (a publisher's
signal, not the probe's). Saved rows are judged on headline + body head,
rejected rows on the headline (their body was never stored).

Measured: agreement on saves (the judge says news: a precision proxy), on
rejects (the judge says soft: a recall proxy), per source x category, and the
topic agreement on saves. Persisted: one `crawl_log` row (website 'ALL', task
'filter_drift_audit') and `crawler_health/filter_drift_<date>.json` with every
disagreeing row. Alert (Telegram): either agreement under AUDIT_MIN_AGREEMENT_SAVED/_REJECTED
(per side, calibrated -- see MIN_AGREEMENT), or a source x category with >= AUDIT_CELL_MIN_N (20) decisions under
AUDIT_CELL_MIN_AGREEMENT (0.80), naming what is NEW since the previous report.

Cost: FILTER_AUDIT_BATCH rows per call (20), at most FILTER_AUDIT_MAX_CALLS
(15) calls, counted in api_usage_log by the labeller.

    python scripts/audit_filter_drift.py --dry-run            # sample only, no key needed
    python scripts/audit_filter_drift.py [--provider openai|gemini] [--days 7]
"""
import argparse
import collections
import json
import logging
import os
import random
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.importance_filter import category_gate  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(REPO_ROOT, "crawler_health")
PER_SIDE = int(os.getenv("FILTER_AUDIT_PER_SIDE", 100))
BATCH = int(os.getenv("FILTER_AUDIT_BATCH", 20))
MAX_CALLS = int(os.getenv("FILTER_AUDIT_MAX_CALLS", 15))
# Per-side floors, calibrated on the first real run (2026-09-29, EXPERIMENTS.md
# "OPS-18: first filter drift audit"): a healthy week measured saved 0.87 and
# rejected 0.78 -- the probe's own test precision/recall (0.94 / 0.87) seen
# through a second labeller, rejects on the headline alone. The ticket's flat
# 0.90 would alert every week. Floors sit ~2 standard errors (n=100: +/-0.04)
# below that baseline, so an alert means a change, not the known error rate.
MIN_AGREEMENT = {"saved": float(os.getenv("AUDIT_MIN_AGREEMENT_SAVED", 0.80)),
                 "rejected": float(os.getenv("AUDIT_MIN_AGREEMENT_REJECTED", 0.70))}
CELL_MIN_N = int(os.getenv("AUDIT_CELL_MIN_N", 20))
CELL_MIN_AGREEMENT = float(os.getenv("AUDIT_CELL_MIN_AGREEMENT", 0.80))
BODY_CHARS = 500

_DECISIONS_SQL = text("""
    SELECT s.sitemap_id, s.sources AS source, s.category, s.headline, s.crawl_status,
           LEFT(a.extracted_text, :body) AS body_head, a.topic
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE s.last_crawl_attempt >= now() - make_interval(days => :days)
      AND ((s.crawl_status = 'saved' AND a.sitemap_id IS NOT NULL) OR s.crawl_status = 'rejected_filter')
      AND s.headline IS NOT NULL
""")


# ── Pure parts (unit-tested) ─────────────────────────────────────────────────

def spread_sample(rows, n, rng):
    """Up to n rows, round-robin across sources (each source's rows shuffled),
    so one high-volume source cannot fill the sample alone."""
    by_source = collections.defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r)
    for bucket in by_source.values():
        rng.shuffle(bucket)
    order = sorted(by_source)
    out = []
    while len(out) < n and any(by_source[s] for s in order):
        for s in order:
            if by_source[s] and len(out) < n:
                out.append(by_source[s].pop())
    return out


def split_decisions(rows):
    """(saved, rejected-by-the-probe). A reject the category gate denied is
    the publisher's signal, not the probe's, and is left out."""
    saved = [r for r in rows if r["crawl_status"] == "saved"]
    rejected = [r for r in rows if r["crawl_status"] == "rejected_filter"
                and category_gate(r["category"], r["source"]) != "deny"]
    return saved, rejected


def agreement(judged):
    """judged: rows with `live_news` (the pipeline's decision) and `judge_news`.
    Returns the summary: per side, per source x category, topic agreement."""
    def rate(rs):
        return sum(r["live_news"] == r["judge_news"] for r in rs) / len(rs) if rs else None
    saves = [r for r in judged if r["live_news"]]
    rejects = [r for r in judged if not r["live_news"]]
    cells = collections.defaultdict(list)
    for r in judged:
        cells[(r["source"], (r["category"] or "").lower())].append(r)
    topic_rows = [r for r in saves if r.get("judge_news") and r.get("topic")]
    return {
        "n_saved": len(saves), "n_rejected": len(rejects),
        "agree_saved": rate(saves), "agree_rejected": rate(rejects),
        "topic_agreement": (sum(r["topic"] == r["judge_topic"] for r in topic_rows) / len(topic_rows)
                            if topic_rows else None),
        "cells": {f"{s}/{c}": {"n": len(rs), "agreement": rate(rs)} for (s, c), rs in cells.items()},
    }


def alerts(summary, previous=None):
    """The reasons to alert, each marked NEW when the previous report did not
    already have it. Empty list = no alert."""
    found = []
    for side in ("saved", "rejected"):
        value = summary[f"agree_{side}"]
        if value is not None and value < MIN_AGREEMENT[side]:
            found.append((f"agreement on {side} {value:.0%} < {MIN_AGREEMENT[side]:.0%}", f"side:{side}"))
    for cell, c in sorted(summary["cells"].items()):
        if c["n"] >= CELL_MIN_N and c["agreement"] is not None and c["agreement"] < CELL_MIN_AGREEMENT:
            found.append((f"{cell}: {c['agreement']:.0%} of {c['n']}", f"cell:{cell}"))
    before = set((previous or {}).get("alert_keys", []))
    return [{"text": t, "key": k, "new": k not in before} for t, k in found]


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_decisions(days):
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    with SQLAlchemyClient().get_session() as s:
        return [dict(r._mapping) for r in s.execute(_DECISIONS_SQL, {"days": days, "body": BODY_CHARS})]


def labeller_module():
    """scripts/label_filter_gold.py: the SYS-36 labeller, reused as the judge."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("label_filter_gold", os.path.join(REPO_ROOT, "scripts", "label_filter_gold.py"))
    lfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lfg)
    return lfg


def judge(lfg, labeller, rows):
    """Adds judge_news/judge_topic to the rows the labeller answered for."""
    from newscrawler.core.filter_rubric import build_label_prompt
    judged, calls = [], 0
    for i in range(0, len(rows), BATCH):
        if calls >= MAX_CALLS:
            logger.warning("FILTER_AUDIT_MAX_CALLS=%d reached; %d row(s) not judged", MAX_CALLS, len(rows) - i)
            break
        batch = rows[i:i + BATCH]
        payload = [{"sitemap_id": r["sitemap_id"], "headline": r["headline"], "body_head": r["body_head"] or ""}
                   for r in batch]
        raw = labeller.call(build_label_prompt(lfg.batch_payload(payload)))
        calls += 1
        labels, problems = lfg.parse_labels(raw, payload)
        if problems:
            logger.warning("batch %d: %s", i // BATCH + 1, "; ".join(problems[:3]))
        for r in batch:
            if r["sitemap_id"] in labels:
                r["judge_news"], r["judge_topic"] = labels[r["sitemap_id"]]
                judged.append(r)
    return judged, calls


def previous_report(today):
    try:
        names = sorted(n for n in os.listdir(REPORT_DIR) if n.startswith("filter_drift_") and n.endswith(".json"))
    except FileNotFoundError:
        return None
    names = [n for n in names if n < f"filter_drift_{today}.json"]
    if not names:
        return None
    with open(os.path.join(REPORT_DIR, names[-1]), encoding="utf-8") as f:
        return json.load(f)


def alert_message(summary, found, judged):
    lines = ["🔎 Filter drift audit (OPS-18): " + ", ".join(
        ("NEW " if a["new"] else "") + a["text"] for a in found)]
    def pct(v):
        return "n/a" if v is None else f"{v:.0%}"
    lines.append(f"saved agreement {pct(summary['agree_saved'])} of {summary['n_saved']}, "
                 f"rejected {pct(summary['agree_rejected'])} of {summary['n_rejected']}")
    examples = [r for r in judged if r["live_news"] != r["judge_news"]][:3]
    for r in examples:
        lines.append(f"- {r['source']}/{r['category']}: {'saved' if r['live_news'] else 'rejected'}, "
                     f"judge says {'news' if r['judge_news'] else 'soft'}: {r['headline'][:90]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--provider", choices=("openai", "gemini"), default="openai")
    ap.add_argument("--dry-run", action="store_true", help="Sample and print; no LLM call, nothing written")
    ap.add_argument("--seed", type=int, default=None, help="default: the ISO week, so a re-run draws the same sample")
    args = ap.parse_args(argv)

    today = date.today().isoformat()
    rng = random.Random(args.seed if args.seed is not None else int(datetime.now().strftime("%G%V")))
    saved, rejected = split_decisions(load_decisions(args.days))
    sample = ([dict(r, live_news=True) for r in spread_sample(saved, PER_SIDE, rng)]
              + [dict(r, live_news=False) for r in spread_sample(rejected, PER_SIDE, rng)])
    logger.info("last %d day(s): %d saved, %d probe rejects; sampled %d", args.days, len(saved), len(rejected), len(sample))
    if args.dry_run:
        for r in sample[:10]:
            logger.info("  %s %s/%s %s", "saved" if r["live_news"] else "rejected", r["source"], r["category"],
                        (r["headline"] or "")[:80])
        return 0

    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    log_ds = SQLAlchemyArticleDataSource(SQLAlchemyClient())
    log_id = log_ds.log_crawl_start("ALL", "filter_drift_audit")
    try:
        lfg = labeller_module()
        labeller, model = lfg.make_labeller(args.provider)
        judged, calls = judge(lfg, labeller, sample)
        summary = agreement(judged)
        found = alerts(summary, previous_report(today))
        report = {"date": today, "model": model, "calls": calls, "summary": summary,
                  "alert_keys": [a["key"] for a in found],
                  "disagreements": [{k: r.get(k) for k in ("sitemap_id", "source", "category", "headline", "live_news",
                                                             "judge_news", "topic", "judge_topic")}
                                    for r in judged if r["live_news"] != r["judge_news"]]}
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, f"filter_drift_{today}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
        note = (f"saved {summary['agree_saved']}, rejected {summary['agree_rejected']}, topic "
                f"{summary['topic_agreement']}; {len(report['disagreements'])} disagreement(s); "
                f"alerts: {[a['text'] for a in found]} -> {path}")[:1000]
        log_ds.log_crawl_complete(log_id, len(judged), note=note)
        logger.info("%s", note)
        if found:
            sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
            from notify_telegram import send
            send(alert_message(summary, found, judged))
        return 0
    except Exception as e:  # noqa: BLE001 -- recorded, then re-raised for the exit code
        log_ds.log_crawl_failed(log_id, f"{type(e).__name__}: {e}"[:1000])
        raise


if __name__ == "__main__":
    sys.exit(main())
