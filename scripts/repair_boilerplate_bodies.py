#!/usr/bin/env python3
r"""
SYS-73 (#223): clean the bodies already stored. Step 1 of 2, and read-only.

The SYS-63 cleaner (`clean_body_paragraphs`) fixes rows saved from 2026-10-04
on; 41% of the 84,606 stored articles still carry other stories' headlines or
page chrome, and so do 163,696 of their 411,994 chunks, in the text RAG search
retrieves and the extractor reads. This step reports what the cleaner would do
to every stored `articles.extracted_text`, writes nothing, and saves the report
for the owner to approve.

    venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py            # the dry run (the only mode)
    venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py --source KOMPAS --top 80

It prints, per source, how many bodies would change, how many would be left
empty or nearly empty (a body the cleaner reduces to nothing is a page that was
only chrome -- the owner decides whether such an article stays), the share of
characters removed, and the chunk rows those articles own. Then the most
frequent removed lines and the longest removed lines: the second list is the one
to read for real sentences, which is how SYS-72 was found. The report goes to
crawler_health/boilerplate-repair-dryrun-<date>.json.

The write step (rewrite `articles.extracted_text`, delete the changed articles'
chunk rows and their vectors, re-chunk, re-embed) is not here yet: it needs the
owner's approval of this report, a fresh `scripts/backup_db.py` dump, and the
run lock and generation checks every FAISS writer has (OPS-26, SYS-53, SYS-56).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.utils.utils import clean_body_paragraphs, is_boilerplate_line  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

REPORT_DIR = os.path.join(ROOT, "crawler_health")
NEARLY_EMPTY_CHARS = 200     # a cleaned body shorter than this is reported as nearly empty
BATCH = 2000
BACA = re.compile(r"baca juga", re.IGNORECASE)
CHROME = re.compile(r"advertisement|scroll to continue|google news|whatsapp channel|ikuti kami|gulir untuk|\[gambas:",
                    re.IGNORECASE)


class SourceStats:
    __slots__ = ("n", "changed", "emptied", "nearly_empty", "chars_before", "chars_after", "baca_before",
                 "baca_after", "chrome_before", "chrome_after")

    def __init__(self):
        for slot in self.__slots__:
            setattr(self, slot, 0)


def assess(body):
    """(cleaned body, the lines the cleaner removed). Pure; the unit under test."""
    body = body or ""
    cleaned = clean_body_paragraphs(body) or ""
    removed = [line.strip() for line in body.split("\n") if line.strip() and is_boilerplate_line(line)]
    return cleaned, removed


def tally(stats, body, cleaned):
    stats.n += 1
    stats.changed += cleaned != body
    stats.emptied += not cleaned.strip() and bool(body.strip())
    stats.nearly_empty += 0 < len(cleaned.strip()) < NEARLY_EMPTY_CHARS <= len(body.strip())
    stats.chars_before += len(body)
    stats.chars_after += len(cleaned)
    stats.baca_before += bool(BACA.search(body))
    stats.baca_after += bool(BACA.search(cleaned))
    stats.chrome_before += bool(CHROME.search(body))
    stats.chrome_after += bool(CHROME.search(cleaned))


def fold(line):
    """A removed line with its digits folded, so 'Baca juga: harga emas 12 ...' groups."""
    return re.sub(r"\d+", "#", line)[:110]


def run(rows, top):
    """rows: iterable of (sitemap_id, source, body). Returns the report dict."""
    per_source = defaultdict(SourceStats)
    removed_counts = Counter()
    longest = []                      # (length, source, line)
    changed_ids = defaultdict(list)
    for sitemap_id, source, body in rows:
        body = body or ""
        cleaned, removed = assess(body)
        tally(per_source[source], body, cleaned)
        if cleaned != body:
            changed_ids[source].append(sitemap_id)
        for line in removed:
            removed_counts[fold(line)] += 1
            if len(line) >= 160:
                longest.append((len(line), source, line[:300]))
    longest.sort(reverse=True)
    return {
        "sources": {s: {k: getattr(st, k) for k in SourceStats.__slots__} for s, st in sorted(per_source.items())},
        "top_removed": removed_counts.most_common(top),
        "longest_removed": longest[:top],
        "changed_ids": changed_ids,
    }


def chunk_counts(session, changed_ids):
    """{source: (chunk rows, L1 rows)} owned by the articles that would change."""
    out = {}
    for source, ids in changed_ids.items():
        total = l1 = 0
        for i in range(0, len(ids), 5000):
            row = session.execute(text(
                "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE chunk_level = 1) AS l1 "
                "FROM chunks WHERE sitemap_id = ANY(:ids)"), {"ids": ids[i:i + 5000]}).fetchone()
            total, l1 = total + row.n, l1 + row.l1
        out[source] = (total, l1)
    return out


def render(report, chunks, top):
    lines = [f"{'source':16s}{'articles':>9s}{'changed':>9s}{'%':>6s}{'emptied':>9s}{'<200ch':>8s}"
             f"{'chars -%':>9s}{'baca b/a %':>13s}{'chrome b/a %':>14s}{'chunk rows':>11s}"]
    totals = SourceStats()
    for source, st in sorted(report["sources"].items(), key=lambda kv: -kv[1]["changed"]):
        n = max(1, st["n"])
        for k in SourceStats.__slots__:
            setattr(totals, k, getattr(totals, k) + st[k])
        lines.append(f"{source:16s}{st['n']:9d}{st['changed']:9d}{100 * st['changed'] / n:6.1f}{st['emptied']:9d}"
                     f"{st['nearly_empty']:8d}{100 * (st['chars_before'] - st['chars_after']) / max(1, st['chars_before']):9.2f}"
                     f"{100 * st['baca_before'] / n:7.1f}/{100 * st['baca_after'] / n:<5.1f}"
                     f"{100 * st['chrome_before'] / n:8.1f}/{100 * st['chrome_after'] / n:<5.1f}"
                     f"{chunks.get(source, (0, 0))[0]:11d}")
    n = max(1, totals.n)
    lines.append(f"{'TOTAL':16s}{totals.n:9d}{totals.changed:9d}{100 * totals.changed / n:6.1f}{totals.emptied:9d}"
                 f"{totals.nearly_empty:8d}{100 * (totals.chars_before - totals.chars_after) / max(1, totals.chars_before):9.2f}"
                 f"{100 * totals.baca_before / n:7.1f}/{100 * totals.baca_after / n:<5.1f}"
                 f"{100 * totals.chrome_before / n:8.1f}/{100 * totals.chrome_after / n:<5.1f}"
                 f"{sum(c[0] for c in chunks.values()):11d}")
    lines.append(f"\nmost frequent removed lines (digits folded to #), top {top}:")
    lines += [f"{count:8d}  {line}" for line, count in report["top_removed"]]
    lines.append(f"\nlongest removed lines (>= 160 chars: read these for real sentences), top {top}:")
    lines += [f"{length:5d}  {source:14s} {line}" for length, source, line in report["longest_removed"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="One source only (default: all)")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--report-dir", default=REPORT_DIR)
    args = parser.parse_args(argv)

    sql = text("SELECT s.sitemap_id, s.sources AS source, a.extracted_text AS body "
               "FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id "
               + ("WHERE s.sources = :source " if args.source else "") + "ORDER BY s.sitemap_id")
    client = SQLAlchemyClient()
    with client.get_session() as session:
        result = session.execute(sql.execution_options(stream_results=True),
                                 {"source": args.source.upper()} if args.source else {})
        report = run(((r.sitemap_id, r.source, r.body) for r in result), args.top)
    with client.get_session() as session:
        chunks = chunk_counts(session, report["changed_ids"])
    print(render(report, chunks, args.top))

    os.makedirs(args.report_dir, exist_ok=True)
    path = os.path.join(args.report_dir, "boilerplate-repair-dryrun-%s.json" % datetime.now(timezone.utc).date())
    out = {k: v for k, v in report.items() if k != "changed_ids"}
    out["chunk_rows"] = {s: {"all": c[0], "l1": c[1]} for s, c in chunks.items()}
    out["changed_sitemap_ids"] = {s: ids for s, ids in report["changed_ids"].items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\nreport -> {path} (nothing was written to the database)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
