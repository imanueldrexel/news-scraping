#!/usr/bin/env python3
"""
SYS-45 (#140): remove saved articles the SYS-37 probe now calls soft.

Two populations, reported separately because they are different decisions:
  --scope allow-since   (SYS-45's own): articles saved under an allow-set
                        category since 2026-09-20 15:20 UTC -- the rows the
                        SYS-35 "never reject" gate waved through before the
                        probe existed (sitemaps.last_crawl_attempt is the
                        fetch stamp; articles has no created_at).
  --scope cosine-era    SYS-48 (#144): articles fetched before the probe went
                        live (2026-09-22 02:10 UTC), i.e. the old cosine
                        filter's corpus; everything later was the probe's own
                        decision.
  --scope all           every saved article the probe calls soft -- the old
                        cosine score's accumulated noise across the corpus
                        (24.4% on the 2026-09-22 backfill dry-run). A far
                        bigger delete; the owner decides whether at all.

Verdicts come from the probe. By default they are re-derived from the
backfill's backup (backups/sys37_topic_backfill_applied_*.json records is_news
per articles_id) so this does not re-embed 11,700 rows through e5-large;
--recompute runs the live filter instead (30 min on CPU).

DBT-34 (#150): the cached verdicts carry the probe's identity -- encoder,
effective tau, gold sha256 and the sha256 of importance_probe.npz -- and this
script refuses to delete anything when they do not match the artifact committed
now. A retrain, a threshold move or an artifact swapped in from an experiment
branch therefore stops the run instead of quietly deleting on the old probe's
opinion. A verdict file written before DBT-34 has no identity and is refused
the same way: re-run --backfill, or use --recompute.

The delete itself is cleanup_offtopic_articles.py's machinery: JSON backup of
the articles + chunks about to go, SQL delete of articles/chunks/entity
mentions-free rows and the sitemaps status flip to rejected_filter, then the
FAISS vectors. Rows referenced by entity_mentions are skipped and counted.

    python scripts/cleanup_soft_by_probe.py --dry-run [--scope allow-since|all] [--sample 50]
    python scripts/cleanup_soft_by_probe.py --scope allow-since          # after the owner's go
    python scripts/cleanup_soft_by_probe.py --scope cosine-era --recompute --min-p-soft 0.9 [--dry-run]

--min-p-soft X (SYS-48) keeps only the soft articles whose P(soft) is at least
X -- the band a hand-read sample showed is safe to delete. It needs --recompute:
only a live score carries P(soft).
"""
import argparse
import collections
import glob
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.importance_filter import category_gate  # noqa: E402
from newscrawler.core.importance_probe import PROBE_BODY_CHARS, build_check_text  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
ALLOW_SINCE = datetime(2026, 9, 20, 15, 20, tzinfo=timezone.utc)
PROBE_LIVE_AT = datetime(2026, 9, 22, 2, 10, tzinfo=timezone.utc)

_ARTICLES_SQL = text("""
    SELECT a.articles_id, a.sitemap_id, s.sources, s.category, s.headline, s.last_crawl_attempt,
           LEFT(a.extracted_text, :n) AS body_head,
           EXISTS (SELECT 1 FROM entity_mentions m WHERE m.sitemap_id = a.sitemap_id) AS referenced
    FROM articles a JOIN sitemaps s USING (sitemap_id)
    ORDER BY a.articles_id
""")


def latest_backfill_backup():
    # Both names on purpose: the pre-DBT-34 files are still on disk and must be
    # *found and refused* for having no identity, not silently skipped as if no
    # verdicts existed at all.
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "sys37_topic_backfill_*.json")))
    return files[-1] if files else None


def verdicts_from_backup(path):
    """(verdicts, meta). `meta` is None for a pre-DBT-34 file -- a bare JSON
    list of rows with no record of which probe produced them."""
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):          # legacy shape, no identity
        return {r["articles_id"]: bool(r["is_news"]) for r in payload}, None
    rows = payload.get("rows", [])
    return {r["articles_id"]: bool(r["is_news"]) for r in rows}, payload.get("meta")


# The fields that must match for cached verdicts to still be this probe's.
# `trained_at` is informational and deliberately not compared: a rebuild of the
# same weights is not a different decision.
IDENTITY_FIELDS = ("embedding_model", "soft_threshold", "gold_sha256", "artifact_sha256")


def identity_mismatch(meta, current):
    """DBT-34 (#150): which identity fields disagree, as human-readable lines.
    Empty list = the cached verdicts came from the artifact committed now."""
    if not meta:
        return ["the verdict file records no probe identity (written before DBT-34 #150)"]
    out = []
    for field in IDENTITY_FIELDS:
        want, got = current.get(field), meta.get(field)
        if isinstance(want, float) or isinstance(got, float):
            same = want is not None and got is not None and abs(float(want) - float(got)) < 1e-9
        else:
            same = want == got
        if not same:
            out.append(f"{field}: verdicts say {got!r}, committed artifact is {want!r}")
    return out


def verdicts_recomputed(rows, soft_threshold=None, p_soft_out=None):
    from newscrawler.core.importance_filter import SemanticImportanceFilter
    # DBT-37 (#153): same construction as the live service, or this scores at
    # the sidecar's tau while the pipeline runs at the env override's.
    filt = SemanticImportanceFilter(soft_threshold=soft_threshold)
    out = {}
    for i in range(0, len(rows), 256):
        chunk = rows[i:i + 256]
        decisions = filt.classify_batch([build_check_text(r.headline, r.body_head) for r in chunk],
                                        [r.category for r in chunk], [r.sources for r in chunk])
        # DBT-36 (#152): this pairing decides which production articles are
        # deleted. Assert the length at the delete boundary as well as inside
        # the filter, so a future regression fails here instead of attributing
        # every verdict after a gap to the wrong article.
        if len(decisions) != len(chunk):
            raise RuntimeError(f"classify_batch returned {len(decisions)} decisions for {len(chunk)} article(s)")
        out.update({r.articles_id: d.is_important for r, d in zip(chunk, decisions)})
        if p_soft_out is not None:
            p_soft_out.update({r.articles_id: d.p_soft for r, d in zip(chunk, decisions)})
    return out


def in_scope(row, scope):
    if scope == "all":
        return True
    stamp = row.last_crawl_attempt
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if scope == "cosine-era":
        return stamp is not None and stamp < PROBE_LIVE_AT
    return category_gate(row.category, row.sources) == "allow" and stamp is not None and stamp >= ALLOW_SINCE


def select(rows, verdicts, scope, p_soft=None, min_p_soft=None):
    """(scoped, soft, unknown, referenced, deletable) -- pure, for the tests.
    With `min_p_soft`, a soft article counts only when its P(soft) (from
    `p_soft`, articles_id -> probability) is at least that."""
    scoped = [r for r in rows if in_scope(r, scope)]
    soft = [r for r in scoped if verdicts.get(r.articles_id) is False]
    if min_p_soft is not None:
        soft = [r for r in soft if (p_soft or {}).get(r.articles_id) is not None
                and p_soft[r.articles_id] >= min_p_soft]
    unknown = [r for r in scoped if r.articles_id not in verdicts]
    referenced = [r for r in soft if r.referenced]
    deletable = [r for r in soft if not r.referenced]
    return scoped, soft, unknown, referenced, deletable


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scope", choices=("allow-since", "cosine-era", "all"), default="allow-since")
    parser.add_argument("--min-p-soft", type=float, default=None,
                        help="SYS-48: only soft articles with P(soft) >= this (needs --recompute)")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--recompute", action="store_true", help="Run the live filter instead of reading the backfill backup")
    parser.add_argument("--seed", type=int, default=20260922)
    args = parser.parse_args(argv)
    if args.min_p_soft is not None and not args.recompute:
        parser.error("--min-p-soft needs --recompute: cached verdicts carry no P(soft)")

    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        rows = session.execute(_ARTICLES_SQL, {"n": PROBE_BODY_CHARS}).fetchall()

    from newscrawler.core.constants import SOFT_THRESHOLD
    from newscrawler.core.importance_probe import artifact_identity

    # The artifact committed right now, at the tau the live pipeline runs at.
    current = artifact_identity(soft_threshold=SOFT_THRESHOLD)
    logger.info("committed probe: %s tau=%.2f gold=%s artifact=%s", current["embedding_model"],
                current["soft_threshold"], (current["gold_sha256"] or "?")[:12], current["artifact_sha256"][:12])

    p_soft = {}
    if args.recompute:
        if args.scope == "cosine-era":   # score only what can be selected (30 min -> ~1/5)
            rows = [r for r in rows if in_scope(r, args.scope)]
        verdicts = verdicts_recomputed(rows, soft_threshold=SOFT_THRESHOLD, p_soft_out=p_soft)
        logger.info("verdicts recomputed through the live filter for %d articles", len(verdicts))
    else:
        path = latest_backfill_backup()
        if not path:
            logger.error("no backups/sys37_topic_backfill_*.json -- run the backfill or pass --recompute")
            return 1
        verdicts, meta = verdicts_from_backup(path)
        logger.info("verdicts from %s (%d articles)", os.path.basename(path), len(verdicts))
        # DBT-34 (#150): this script deletes articles, their chunks and their
        # FAISS vectors, and flips their sitemaps to the terminal
        # rejected_filter. Doing that on verdicts from a probe that is no longer
        # the committed one is unrecoverable and, before this check, silent --
        # the log line only ever said which file it read.
        problems = identity_mismatch(meta, current)
        if problems:
            logger.error("REFUSING to act on %s -- it was not produced by the committed probe:",
                         os.path.basename(path))
            for line in problems:
                logger.error("  %s", line)
            logger.error("Re-run `train_importance_probe.py --backfill` to refresh the verdicts, "
                         "or pass --recompute to score through the live filter now.")
            return 1
        logger.info("verdict file matches the committed probe (%s)", ", ".join(IDENTITY_FIELDS))

    scoped, soft, unknown, referenced, deletable = select(rows, verdicts, args.scope, p_soft, args.min_p_soft)
    logger.info("scope %s: %d articles; probe says soft: %d (%.1f%%); %d referenced by entity_mentions (kept); "
                "%d deletable; %d without a verdict (saved after the backfill -- rerun it or --recompute)",
                args.scope, len(scoped), len(soft), 100 * len(soft) / max(1, len(scoped)), len(referenced), len(deletable), len(unknown))
    by = collections.Counter((r.sources, r.category) for r in deletable)
    for (src, cat), n in by.most_common(25):
        logger.info("  %-15s %-24s %5d", src, cat, n)
    rng = random.Random(args.seed)
    for r in rng.sample(deletable, min(args.sample, len(deletable))):
        logger.info("  SOFT  %-14s %-16s %s", r.sources, (r.category or "")[:16], (r.headline or "")[:95])

    if args.dry_run or not deletable:
        logger.info("[dry-run] would delete %d article(s) (+ their chunks and FAISS vectors) and mark their sitemaps rejected_filter. Nothing written.", len(deletable))
        return 0

    from scripts.cleanup_offtopic_articles import delete_articles  # the SYS-31/SYS-34 machinery: backup -> SQL -> FAISS
    tag = f"sys45_soft_by_probe_{args.scope}" + (f"_p{args.min_p_soft:g}" if args.min_p_soft is not None else "")
    n = delete_articles(client, [r.sitemap_id for r in deletable], backup_tag=tag)
    logger.info("deleted %d article(s); sitemaps -> rejected_filter; backup in %s", n, BACKUP_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
