#!/usr/bin/env python3
r"""
SYS-91 (#257): make the FAISS documents' `posted_at` metadata equal `sitemaps.posted_at`.

SYS-90 repaired `articles.meta_data.posted_at` of the CNBC rows that pydantic 2 had dated
1970-08-23 (an int yyyymmdd read as Unix seconds). The chunker had already written the same date
into the vectors' metadata: 88 L1 and 104 L2 documents, all CNBC (QA, 2026-10-06). The search page
takes dates from the database (SYS-92) and reads this value only when that query fails, so this is
the stores agreeing again, not a reader-visible fix.

  Step 1, the dry run (the default), is read-only: every document whose `posted_at` differs from its
  sitemap's, by index, kind (19xx / empty / other) and source.

      venv\Scripts\python.exe scripts\repair_faiss_posted_at.py

  Step 2, `--apply`, holding the run lock throughout:
    1. back up NEWS_L1/NEWS_L2 and the sitemaps' rows (backups/sys91_ALL_<stamp>/);
    2. rewrite the targets' metadata in place and save each index (atomic, generation-checked).
       Nothing is re-embedded: vector ids and positions do not move.
  By default only the `19xx` documents are targets (the ticket); `--all-mismatches` widens it to every
  kind, after the owner has read the dry run. A second run finds nothing.

  Exit: 0 done, 2 refused (a crawl holds the run lock, or a crawl_log row is 'started').
"""
import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
# DBT-67 (ADR-015): the shared repair steps, imported by name (redirect store_repair.BACKUP_DIR, not a copy).
from newscrawler.tools.store_repair import NoEmbeddings, backup, crawl_running, faiss_dirs  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

STORED_SQL = text("SELECT sitemap_id, posted_at FROM sitemaps WHERE sitemap_id = ANY(:ids)")


def kind(value: str) -> str:
    if not value:
        return "empty"
    return "19xx" if value.startswith("19") else "other"


def select_targets(docs, stored):
    """Pure. `docs`: (doc_id, metadata); `stored`: {sitemap_id: int yyyymmdd}. The documents whose
    `posted_at` differs from their sitemap's, as (doc_id, sitemap_id, old, new, kind, source). A
    document whose sitemap is gone or has no date is left alone (nothing to copy)."""
    out = []
    for doc_id, meta in docs:
        sid = meta.get("sitemap_id")
        want = stored.get(int(sid)) if sid is not None else None
        if not want:
            continue
        old, new = str(meta.get("posted_at") or ""), str(want)
        if old == new:
            continue
        out.append((doc_id, int(sid), old, new, kind(old), meta.get("source", "")))
    return out


def to_write(mismatches, only_1970=True):
    """The mismatches a write rewrites: the 19xx ones (the ticket) unless widened."""
    return [t for t in mismatches if not only_1970 or t[4] == "19xx"]


def _load(db):
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    return load_index(db, NoEmbeddings())


def _stored_dates(client, stores):
    ids = sorted({int(d.metadata["sitemap_id"]) for s in stores.values() for d in s.docstore._dict.values()
                  if d.metadata.get("sitemap_id") is not None})
    stored = {}
    with client.get_session() as session:
        for start in range(0, len(ids), 50000):
            stored.update({r.sitemap_id: r.posted_at for r in session.execute(STORED_SQL, {"ids": ids[start:start + 50000]})})
    return stored


def find(client, stores):
    """{db: every mismatch} for every loaded index."""
    stored = _stored_dates(client, stores)
    return {db: select_targets(((i, d.metadata) for i, d in s.docstore._dict.items()), stored)
            for db, s in stores.items()}


def report(found, only_1970):
    """Every mismatch, by kind and source, and how many of them a write would rewrite."""
    lines = []
    for db, mismatches in found.items():
        written = to_write(mismatches, only_1970)
        lines.append("%s: %d document(s) whose posted_at differs from sitemaps.posted_at; %d would be "
                     "rewritten%s" % (db, len(mismatches), len(written), " (19xx only)" if only_1970 else ""))
        lines.append("  by kind: %s" % dict(Counter(t[4] for t in mismatches)))
        lines.append("  by source: %s" % dict(Counter(t[5] for t in mismatches)))
        lines.append("  sitemaps: %d; e.g. %s" % (len({t[1] for t in mismatches}),
                                                  [(t[1], t[2], t[3]) for t in mismatches[:3]]))
    return "\n".join(lines)


def apply(args, client=None) -> int:
    from newscrawler.tools.run_lock import RunLock, RunLockHeld
    client = client or SQLAlchemyClient()
    try:
        with RunLock(purpose="SYS-91 repair FAISS posted_at"):
            return _apply_locked(args, client)
    except RunLockHeld as e:
        logger.error("refusing to write: %s", e)
        return 2


def _apply_locked(args, client) -> int:
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        if crawl_running(session):
            logger.error("a crawl_log row is 'started' in the last 4 h; refusing to rewrite FAISS under a running crawl")
            return 2
    dirs = faiss_dirs()
    stores = {db: _load(db) for db in dirs}
    only_1970 = not args.all_mismatches
    mismatches = find(client, stores)
    print(report(mismatches, only_1970))
    found = {db: to_write(ms, only_1970) for db, ms in mismatches.items()}
    summary = {db: 0 for db in dirs}
    if any(found.values()):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pairs = sorted({(t[1], None) for targets in found.values() for t in targets})
        summary["backup"] = backup(client, "ALL", pairs, dirs, stamp, tag="sys91")
        for db, targets in found.items():
            if not targets:
                continue
            docs = stores[db].docstore._dict
            for doc_id, _, _, new, _, _ in targets:
                docs[doc_id].metadata["posted_at"] = new
            ChunkFAISSDatasource._atomic_save_local(stores[db], db)
            summary[db] = len(targets)
            logger.info("%s: rewrote posted_at of %d document(s), saved", db, len(targets))
    logger.info("SUMMARY: %s", json.dumps(summary))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write (default: the dry run)")
    parser.add_argument("--all-mismatches", action="store_true",
                        help="Every kind of mismatch, not only the 19xx documents (read the dry run first)")
    args = parser.parse_args(argv)
    if args.apply:
        # OPS-26/DBT-43: this writes NEWS_L1/L2; refuse at the door while a crawl holds the run lock,
        # before the database or the indexes are touched.
        from newscrawler.tools.run_lock import refused_by_run_lock
        if refused_by_run_lock(logger):
            return 2
        return apply(args)
    stores = {db: _load(db) for db in faiss_dirs()}
    print(report(find(SQLAlchemyClient(), stores), only_1970=not args.all_mismatches))
    print("\n(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
