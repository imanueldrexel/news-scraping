"""SYS-39 (#125) bake-off: does a candidate provider extract the same entities as the reference?

Three steps, each its own subcommand, all reading and writing JSON lines:

  fixture   Draw N stored articles, stratified by articles.topic, with their text
            cut as production cuts it. Read-only on Postgres. The fixture is
            committed (tests/fixtures/extraction_bakeoff.jsonl) so every provider
            is scored on the same 200 articles.
  run       Send the production prompt for every fixture article to one provider
            and record the parsed reply, the tokens it reported, the latency and
            what failed (a parse failure, a transient error, a quota 429). Writes
            nothing to Postgres: no article is marked extracted, no usage is logged.
            A priced provider is refused inside the peak window unless --allow-peak.
  score     Compare two runs: per type (persons, organizations, locations) the
            precision, recall and F1 of the candidate's normalised names against
            the reference's, pooled F1 over the three, and event_type agreement.
            Exit 1 when pooled F1 is under --min-agreement (default 0.85).

    venv\\Scripts\\python.exe scripts\\experiments\\bakeoff_extraction.py fixture --n 200
    venv\\Scripts\\python.exe scripts\\experiments\\bakeoff_extraction.py run --provider openai --out runs\\deepseek_1.jsonl
    venv\\Scripts\\python.exe scripts\\experiments\\bakeoff_extraction.py score runs\\deepseek_1.jsonl runs\\deepseek_2.jsonl

Run a provider against itself (two runs) to measure the ceiling: the production
Gemini model agrees with itself at only 0.53 (OPS-20), so 0.85 against a single
noisy reference is not reachable by any candidate.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

DEFAULT_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "extraction_bakeoff.jsonl")
TYPES = ("persons", "organizations", "locations")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── fixture ──────────────────────────────────────────────────────────────────

def stratified(rows_by_topic, n, seed):
    """n rows, as even across topics as the topics allow (a topic with fewer rows
    than its share gives all it has; the shortfall is spread over the others)."""
    rng = random.Random(seed)
    pools = {t: rng.sample(rows, len(rows)) for t, rows in sorted(rows_by_topic.items())}
    picked = []
    while len(picked) < n and any(pools.values()):
        for topic in list(pools):
            if pools[topic] and len(picked) < n:
                picked.append(pools[topic].pop())
    return picked


def cmd_fixture(args):
    from sqlalchemy import text
    from newscrawler.core.knowledge_extractor import ARTICLE_CHARS
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    with SQLAlchemyClient().get_session() as session:
        rows = session.execute(text(
            "SELECT a.articles_id, a.topic, s.sources, s.headline, LEFT(a.extracted_text, :n) AS body "
            "FROM articles a JOIN sitemaps s USING (sitemap_id) "
            "WHERE a.topic IS NOT NULL AND LENGTH(a.extracted_text) >= :min_chars "
            "AND s.posted_at >= :since"), {"n": ARTICLE_CHARS, "min_chars": args.min_chars,
                                           "since": args.since}).fetchall()
    by_topic = {}
    for r in rows:
        by_topic.setdefault(r.topic, []).append({
            "article_id": r.articles_id, "topic": r.topic, "source": r.sources, "headline": r.headline,
            "text": r.body})
    picked = stratified(by_topic, args.n, args.seed)
    _write(args.out, picked)
    counts = {t: sum(1 for p in picked if p["topic"] == t) for t in sorted(by_topic)}
    print(f"{len(picked)} articles from {len(rows)} candidates -> {args.out}\nper topic: {counts}")
    return 0


# ── run ──────────────────────────────────────────────────────────────────────

def one_call(provider, row):
    from newscrawler.core.extraction_provider import ProviderQuotaExhausted, ProviderTransientError
    from newscrawler.core.knowledge_extractor import build_prompt, parse_extraction
    started = time.monotonic()
    out = {"article_id": row["article_id"], "topic": row["topic"], "parsed": None, "input_tokens": 0,
           "output_tokens": 0, "error": None, "error_kind": None, "no_text": False}
    try:
        completion = provider.complete(build_prompt(row["text"]))
        out["input_tokens"], out["output_tokens"] = completion.input_tokens, completion.output_tokens
        out["no_text"] = completion.text is None
        out["parsed"] = parse_extraction(completion.text)
    except ProviderQuotaExhausted as e:
        out["error"], out["error_kind"] = str(e)[:300], "quota"
    except ProviderTransientError as e:
        out["error"], out["error_kind"] = str(e)[:300], "transient"
    out["latency_s"] = round(time.monotonic() - started, 3)
    return out


def summarize(results, wall_s, priced, peak):
    from newscrawler.core.peak_hours import cost_usd
    n = len(results)
    answered = [r for r in results if r["error_kind"] is None]
    parse_failures = [r for r in answered if r["parsed"] is None]
    lat = sorted(r["latency_s"] for r in answered) or [0.0]
    tin, tout = sum(r["input_tokens"] for r in results), sum(r["output_tokens"] for r in results)
    lines = [
        f"articles           {n}",
        f"answered           {len(answered)}  (parse failures {len(parse_failures)} = "
        f"{len(parse_failures) / max(1, len(answered)):.1%}, of which empty reply "
        f"{sum(1 for r in answered if r['no_text'])})",
        f"transient errors   {sum(1 for r in results if r['error_kind'] == 'transient')}",
        f"quota errors       {sum(1 for r in results if r['error_kind'] == 'quota')}",
        f"tokens             {tin} in / {tout} out  ({tin / max(1, len(answered)):.0f} / "
        f"{tout / max(1, len(answered)):.0f} per answered article)",
        f"latency            p50 {statistics.median(lat):.1f}s  p95 {lat[int(0.95 * (len(lat) - 1))]:.1f}s",
        f"wall clock         {wall_s:.0f}s  ({wall_s / max(1, n) * 1000:.0f}s per 1,000 articles)",
    ]
    if priced:
        total = cost_usd(tin, tout, peak)
        lines.append(f"cost               ${total:.4f}  (${total / max(1, len(answered)) * 1000:.3f} per 1,000 "
                     f"answered, {'peak' if peak else 'off-peak'} price)")
    return "\n".join(lines)


def cmd_run(args):
    from newscrawler.core.extraction_provider import build_provider
    from newscrawler.core.peak_hours import is_peak
    provider = build_provider(args.provider)
    if provider is None:
        print(f"provider {args.provider!r} has no credentials in .env", file=sys.stderr)
        return 2
    peak = is_peak(datetime.now(timezone.utc))
    if provider.priced and peak and not args.allow_peak:
        print("refusing: the provider's peak window is open (doubles the price); wait or pass --allow-peak",
              file=sys.stderr)
        return 2
    rows = _read(args.fixture)[: args.limit or None]
    print(f"{provider.name}: {len(rows)} articles, {args.workers} workers"
          f"{', PEAK PRICE' if provider.priced and peak else ''}", flush=True)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda r: one_call(provider, r), rows))
    wall = time.monotonic() - started
    _write(args.out, results)
    print(summarize(results, wall, provider.priced, peak))
    print(f"-> {args.out}")
    return 0


# ── score ────────────────────────────────────────────────────────────────────

def names(parsed, kind, normalize):
    return {n for n in (normalize(str(e.get("name", ""))) for e in (parsed.get(kind) or []) if isinstance(e, dict)) if n}


def score(reference, candidate, normalize):
    """{type: (tp, fp, fn)} pooled over the articles both runs parsed, the number of
    such articles, and event_type agreement over them."""
    ref = {r["article_id"]: r["parsed"] for r in reference if r["parsed"] is not None}
    cand = {r["article_id"]: r["parsed"] for r in candidate if r["parsed"] is not None}
    both = sorted(ref.keys() & cand.keys())
    counts = {t: [0, 0, 0] for t in TYPES}
    events = 0
    for aid in both:
        for t in TYPES:
            a, b = names(ref[aid], t, normalize), names(cand[aid], t, normalize)
            counts[t][0] += len(a & b)
            counts[t][1] += len(b - a)
            counts[t][2] += len(a - b)
        events += normalize(str(ref[aid].get("event_type") or "")) == normalize(str(cand[aid].get("event_type") or ""))
    return counts, len(both), events


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def cmd_score(args):
    from newscrawler.core.entity_normalizer import EntityNormalizer
    normalize = EntityNormalizer().normalize
    reference, candidate = _read(args.reference), _read(args.candidate)
    counts, n, events = score(reference, candidate, normalize)
    print(f"reference {args.reference}  vs  candidate {args.candidate}: {n} articles parsed by both "
          f"(reference {sum(1 for r in reference if r['parsed'] is not None)}/{len(reference)}, "
          f"candidate {sum(1 for r in candidate if r['parsed'] is not None)}/{len(candidate)})")
    print(f"{'type':<14}{'precision':>10}{'recall':>8}{'F1':>7}")
    for t in TYPES:
        p, r, f = prf(*counts[t])
        print(f"{t:<14}{p:>10.3f}{r:>8.3f}{f:>7.3f}")
    pooled = prf(*[sum(counts[t][i] for t in TYPES) for i in range(3)])
    print(f"{'pooled':<14}{pooled[0]:>10.3f}{pooled[1]:>8.3f}{pooled[2]:>7.3f}")
    print(f"event_type agreement {events / max(1, n):.3f}")
    ok = pooled[2] >= args.min_agreement
    print(f"pooled F1 {pooled[2]:.3f} {'>=' if ok else '<'} {args.min_agreement} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fixture")
    f.add_argument("--n", type=int, default=200)
    f.add_argument("--seed", type=int, default=39)
    f.add_argument("--since", type=int, default=20260928, help="posted_at yyyymmdd lower bound")
    f.add_argument("--min-chars", type=int, default=800)
    f.add_argument("--out", default=DEFAULT_FIXTURE)
    f.set_defaults(fn=cmd_fixture)
    r = sub.add_parser("run")
    r.add_argument("--provider", choices=("openai", "gemini"), required=True)
    r.add_argument("--fixture", default=DEFAULT_FIXTURE)
    r.add_argument("--out", required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--limit", type=int, default=0, help="first N fixture articles only")
    r.add_argument("--allow-peak", action="store_true")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score")
    s.add_argument("reference")
    s.add_argument("candidate")
    s.add_argument("--min-agreement", type=float, default=0.85)
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
