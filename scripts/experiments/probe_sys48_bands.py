#!/usr/bin/env python3
"""
SYS-48 (#144) step 1: the P(soft) distribution of the articles the old cosine
filter saved, scored by the probe committed now.

Population: saved articles whose sitemap was fetched before the SYS-37 probe
went live (sitemaps.last_crawl_attempt < 2026-09-22 02:10 UTC, the backfill
time; articles has no created_at, SYS-45 used the same stamp). Everything saved
later was decided by the probe itself.

Scores each through `SemanticImportanceFilter.classify_batch` (the one
decision function, same construction as the live service), with the same
input the crawl uses (`build_check_text(headline, body)`), and records the
gate, P(soft) and topic. Read-only: writes a JSON of the rows to --out and
prints counts at P(soft) >= 0.6/0.7/0.8/0.9 overall and by source x category.

    venv\\Scripts\\python.exe scripts/experiments/probe_sys48_bands.py --out <path>.json

First run + conclusions: EXPERIMENTS.md, 2026-09-29 "SYS-48: P(soft) bands of the cosine-era corpus".
"""
import argparse
import collections
import json
import os
import sys
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SOFT_THRESHOLD  # noqa: E402
from newscrawler.core.importance_probe import PROBE_BODY_CHARS, build_check_text  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

PROBE_LIVE_AT = "2026-09-22 02:10:00+00"
BANDS = (0.6, 0.7, 0.8, 0.9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(text(f"""
            SELECT a.articles_id, a.sitemap_id, s.sources, s.category, s.headline,
                   LEFT(a.extracted_text, :n) AS body_head,
                   EXISTS (SELECT 1 FROM entity_mentions m WHERE m.sitemap_id = a.sitemap_id) AS referenced
            FROM articles a JOIN sitemaps s USING (sitemap_id)
            WHERE s.last_crawl_attempt < '{PROBE_LIVE_AT}'
            ORDER BY a.articles_id {'LIMIT :lim' if args.limit else ''}"""),
            {"n": PROBE_BODY_CHARS * 4, "lim": args.limit}).fetchall()
    print(f"{len(rows)} cosine-era saved articles (fetched before {PROBE_LIVE_AT})", flush=True)

    from newscrawler.core.importance_filter import SemanticImportanceFilter
    filt = SemanticImportanceFilter(soft_threshold=SOFT_THRESHOLD)
    out, t0 = [], time.monotonic()
    for i in range(0, len(rows), 256):
        chunk = rows[i:i + 256]
        decisions = filt.classify_batch([build_check_text(r.headline, r.body_head) for r in chunk],
                                        [r.category for r in chunk], [r.sources for r in chunk])
        assert len(decisions) == len(chunk)
        for r, d in zip(chunk, decisions):
            out.append({"articles_id": r.articles_id, "sitemap_id": r.sitemap_id, "source": r.sources,
                        "category": r.category, "headline": r.headline, "body_head": (r.body_head or "")[:400],
                        "referenced": r.referenced, "gate": d.gate, "is_news": d.is_important,
                        "p_soft": d.p_soft, "topic": d.topic})
        if (i // 256) % 10 == 0:
            print(f"  {i + len(chunk)}/{len(rows)} in {time.monotonic() - t0:.0f}s", flush=True)

    meta = {"probe_live_at": PROBE_LIVE_AT, "soft_threshold": filt.probe.soft_threshold,
            "sidecar": {k: filt.probe.sidecar.get(k) for k in ("gold_sha256", "embedding_model", "trained_at")}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rows": out}, f, ensure_ascii=False, default=str)

    denied = sum(1 for r in out if r["gate"] == "deny")
    soft = [r for r in out if not r["is_news"]]
    print(f"\n{len(out)} scored; not news now: {len(soft)} ({len(soft) / max(1, len(out)):.1%}); "
          f"of which denied by category: {denied}; tau = {meta['soft_threshold']}")
    for b in BANDS:
        n = sum(1 for r in out if r["p_soft"] is not None and r["p_soft"] >= b)
        print(f"  P(soft) >= {b}: {n}")
    by = collections.Counter((r["source"], r["category"]) for r in out if r["p_soft"] is not None and r["p_soft"] >= 0.8)
    print("\nP(soft) >= 0.8 by source x category (top 25):")
    for (src, cat), n in by.most_common(25):
        print(f"  {src:15} {str(cat)[:30]:30} {n}")


if __name__ == "__main__":
    main()
