#!/usr/bin/env python3
r"""
SYS-73 (#223): clean the bodies already stored.

The SYS-63 cleaner (`clean_body_paragraphs`) fixes rows saved from 2026-10-04
on; 41% of the 84,606 stored articles still carried other stories' headlines or
page chrome, and so did 163,696 of their 411,994 chunks, in the text RAG search
retrieves and the extractor reads.

  Step 1, the dry run (the default), is read-only: it reports what the cleaner would do to
  every stored `articles.extracted_text` and saves the report for the owner to approve.

      venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py
      venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py --source KOMPAS --top 80

  Step 2, `--apply --source NAME`, repairs one source (owner decision 2026-10-04: per source,
  DETIK first). Holding the run lock throughout, in this order:
    1. back up NEWS_L1/NEWS_L2 and the rows about to change (backups/sys73_<source>_<stamp>/);
    2. delete the changed articles' vectors from both indexes (one atomic, generation-checked save each);
    3. one SQL transaction: delete their entity mentions (and reset those articles for extraction), delete
       their chunk rows, write the cleaned text;
    4. re-chunk and re-embed them from the stored text in blocks of --block articles, one FAISS flush per
       block (`deferred_embeddings`), until --until HH:MM (local) if given;
    5. recompute the counters of the entities that lost mentions (SYS-20).
  Killed or stopped at the deadline between 3 and 4, the articles have no chunks and nothing else
  changes: `--rechunk-only` (or scripts/backfill_orphan_chunks.py) finishes the job. The step is
  idempotent: a second run finds no article whose cleaned text differs.

      venv\Scripts\python.exe scripts\repair_boilerplate_bodies.py --apply --source DETIK --until 11:30

  Exit: 0 done, 1 some articles failed to re-chunk, 2 refused (a crawl holds the run lock, or a
  crawl_log row is 'started'), 3 stopped at the deadline with articles left.

The dry run prints, per source, how many bodies would change, how many would be left empty or nearly
empty, the share of characters removed and the chunk rows those articles own, then the most frequent and
the longest removed lines (the second list is the one to read for real sentences, which is how SYS-72
and SYS-75 were found). The report goes to crawler_health/boilerplate-repair-dryrun-<date>.json.
"""
import argparse
import json
import logging
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
# DBT-67 (ADR-015): the shared repair steps. Imported by name, so a test that patches this script's
# name patches this script's call; BACKUP_DIR is read in the module (redirect store_repair.BACKUP_DIR).
from newscrawler.tools.store_repair import (  # noqa: E402
    DEFAULT_BLOCK, MIN_RUN_MINUTES, backup, crawl_running, delete_vectors, faiss_dirs, parse_until, rechunk,
    recount_entity_counts, too_close,
)

REPORT_DIR = os.path.join(ROOT, "crawler_health")

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
NEARLY_EMPTY_CHARS = 200     # a cleaned body shorter than this is reported as nearly empty
BATCH = 2000
BLANK_RUNS = re.compile(r"\n{3,}")
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


# ── SYS-73 step 2: the write path ────────────────────────────────────────────

def select_targets(rows):
    """Pure. `rows`: (sitemap_id, stored body). [(sitemap_id, cleaned body)] for the articles whose
    cleaned body differs from the stored one. An article the cleaner would empty is not rewritten
    (the dry run reports it; deleting an article's whole text is the owner's call)."""
    out = []
    for sitemap_id, body in rows:
        body = body or ""
        cleaned = clean_body_paragraphs(body) or ""
        if cleaned != body and cleaned.strip():
            # A stored body is one string; a removed line leaves its blank line behind. Collapse the
            # runs here, in rows that are being rewritten anyway (a clean body is never touched).
            out.append((sitemap_id, BLANK_RUNS.sub("\n\n", cleaned)))
    return out


def rewrite_rows(session, targets):
    """One transaction: drop the targets' entity mentions (their articles are re-extracted from the
    cleaned text; the counters are recomputed afterwards), drop their chunk rows, write the cleaned text.
    Returns (mentions deleted, articles reset for extraction, chunk rows deleted, articles rewritten)."""
    ids = [sid for sid, _ in targets]
    extracted = [r[0] for r in session.execute(text(
        "SELECT DISTINCT sitemap_id FROM entity_mentions WHERE sitemap_id = ANY(:i)"), {"i": ids})]
    n_mentions = session.execute(text("DELETE FROM entity_mentions WHERE sitemap_id = ANY(:i)"),
                                 {"i": ids}).rowcount
    n_reset = session.execute(text(
        "UPDATE articles SET knowledge_extracted = 0, knowledge_extracted_at = NULL, "
        "knowledge_extract_attempts = 0, last_extract_error = NULL WHERE sitemap_id = ANY(:i)"),
        {"i": extracted}).rowcount if extracted else 0
    n_chunks = session.execute(text("DELETE FROM chunks WHERE sitemap_id = ANY(:i)"), {"i": ids}).rowcount
    for sitemap_id, cleaned in targets:
        session.execute(text("UPDATE articles SET extracted_text = :t WHERE sitemap_id = :i"),
                        {"t": cleaned, "i": sitemap_id})
    session.commit()
    return n_mentions, n_reset, n_chunks, len(targets)


def apply_source(args, client=None, make_repo=None) -> int:
    """The write step for one source. Holds the run lock (a crawl, the newsletter and the extraction
    all wait or refuse meanwhile). Exit: 0 done, 1 failures, 2 refused, 3 stopped at the deadline."""
    source = args.source.upper()
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="boilerplate repair %s" % source):
            return _apply_locked(args, source, client, make_repo)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, source, client, make_repo) -> int:
    # SYS-111: one deadline for the whole run. Resolved again after a rewrite that outlasted it,
    # "HH:MM" would mean tomorrow and the re-chunk would never stop.
    deadline = parse_until(args.until)
    dirs = faiss_dirs()
    if not args.rechunk_only and too_close(deadline):
        logger.error("--until %s is less than %d minutes away; refusing before any backup or delete (SYS-111)",
                     args.until, MIN_RUN_MINUTES)
        return 2
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
        rows = session.execute(text(
            "SELECT a.sitemap_id, a.extracted_text FROM articles a JOIN sitemaps s USING (sitemap_id) "
            "WHERE s.sources = :w ORDER BY a.sitemap_id"), {"w": source}).fetchall()
    targets = [] if args.rechunk_only else select_targets((r.sitemap_id, r.extracted_text) for r in rows)
    logger.info("%s: %d article(s), %d to rewrite", source, len(rows), len(targets))
    summary = {"rewritten": 0, "mentions_deleted": 0, "reset_for_extraction": 0, "chunk_rows_deleted": 0,
               "vectors_deleted": 0}
    if targets:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary["backup"] = backup(client, source, targets, dirs, stamp)
        summary["vectors_deleted"] = sum(delete_vectors(targets, dirs).values())
        with client.get_session() as session:
            m, reset, c, n = rewrite_rows(session, targets)
        summary.update(mentions_deleted=m, reset_for_extraction=reset, chunk_rows_deleted=c, rewritten=n)
        logger.info("rewrote %d article(s); deleted %d chunk row(s) and %d mention(s); %d reset for extraction",
                    n, c, m, reset)
    repaired, empty, failed, left = rechunk(client, source, args.block, deadline, make_repo)
    summary.update(rechunked=repaired, empty=empty, failed=failed, left=left)
    if summary["mentions_deleted"]:
        recount_entity_counts(client)        # SYS-20: the counters of entities that lost mentions
    logger.info("SUMMARY %s: %s", source, json.dumps(summary))
    _notify("Boilerplate repair %s: %d articles rewritten, %d re-chunked, %d failed, %d left%s" % (
        source, summary["rewritten"], repaired, failed, left, " (stopped at the deadline)" if left else ""))
    return 3 if left else (1 if failed else 0)


def _notify(message: str) -> None:
    """Telegram, via the OPS-01 notifier; a failure to notify never changes the result."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from notify_telegram import send
        send(message)
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram notification failed: %s", e)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="One source only (default: all)")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--report-dir", default=REPORT_DIR)
    parser.add_argument("--apply", action="store_true", help="Write: repair --source (default: the dry run)")
    parser.add_argument("--rechunk-only", action="store_true",
                        help="With --apply: only re-chunk the source's articles that have no chunks")
    parser.add_argument("--block", type=int, default=DEFAULT_BLOCK, help="Articles per FAISS flush (default 1000)")
    parser.add_argument("--until", default=None, metavar="HH:MM", help="Stop starting blocks at this local time")
    args = parser.parse_args(argv)

    if args.apply or args.rechunk_only:
        if not args.source:
            parser.error("--apply needs --source (one source at a time)")
        # OPS-26/DBT-43: this writes NEWS_L1/L2; refuse at the door while a crawl holds the run lock,
        # before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply_source(args)

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
