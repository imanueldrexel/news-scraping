#!/usr/bin/env python3
"""
DBT-20 step 1: correct sitemaps.crawl_status for rows marked 'rejected_filter' that
have direct, positive evidence they actually passed the semantic filter -- an L1
FAISS vector already exists for them, and chunking only begins after
SemanticImportanceFilter.is_important() returns True (see
crawler_service_impl.py's _crawl_newsdetails_inner).

'rejected_filter' is meant to be a terminal, permanent classification (SYS-16) --
load_all_sitemaps excludes it forever, on the reasoning that the same
headline/text will fail the same INTERESTS check again. backfill_sitemap_crawl_status.py
approximated that classification for ~73k already-attempted-no-article sitemaps using
only a fresh headline re-check, documented as "a reasonable approximation... not a
re-run of it" -- and for these specific rows, the approximation disagrees with direct
evidence. They cannot be retried (and their L1 vector cannot be joined to a real
chunks/articles row, DBT-20's next step) until this is fixed.

Scope: MEDIAINDONESIA's 1,183 L1-only sitemaps (DBT-20, #70) happen to be the
population this was written for, but the query is general -- any source's sitemap
with an L1 vector and crawl_status='rejected_filter' qualifies, not just
MEDIAINDONESIA's -- so a future recurrence elsewhere is caught by the same run.

Usage:
    python scripts/fix_rejected_filter_with_faiss_evidence.py --dry-run
    python scripts/fix_rejected_filter_with_faiss_evidence.py
    python scripts/fix_rejected_filter_with_faiss_evidence.py --website MEDIAINDONESIA
"""
import argparse
import logging
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import VECTOR_DB_NAME_L1
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def load_l1_sitemap_ids() -> set:
    path = os.path.join(VECTOR_DB_NAME_L1, "index.pkl")
    with open(path, "rb") as f:
        docstore, _ = pickle.load(f)
    return {int(doc.metadata["sitemap_id"]) for doc in docstore._dict.values()
            if doc.metadata.get("sitemap_id") is not None}


def find_misclassified(session, l1_ids: set, website: str = None) -> list:
    """Rows currently 'rejected_filter' whose sitemap_id has a real L1 vector.
    Returns (sitemap_id, sources) tuples. Pure SQL side kept separate from the
    pickle read so this half is trivially unit-testable against a fake session."""
    rows = session.execute(
        text("SELECT sitemap_id, sources FROM sitemaps "
             "WHERE crawl_status = 'rejected_filter' AND sitemap_id = ANY(:ids) "
             "AND (:website IS NULL OR sources = :website)"),
        {"ids": list(l1_ids), "website": website},
    ).fetchall()
    return [(r.sitemap_id, r.sources) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Limit to one source (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    args = parser.parse_args()

    l1_ids = load_l1_sitemap_ids()
    logger.info("L1 FAISS index has %d distinct sitemap_ids", len(l1_ids))

    client = SQLAlchemyClient()
    with client.get_session() as session:
        misclassified = find_misclassified(session, l1_ids, args.website)

    if not misclassified:
        logger.info("Nothing to fix -- no rejected_filter row has L1 FAISS evidence.")
        return 0

    by_source = {}
    for _, source in misclassified:
        by_source[source] = by_source.get(source, 0) + 1
    logger.info("%d misclassified row(s): %s", len(misclassified), by_source)

    if args.dry_run:
        logger.info("[dry-run] Would set crawl_status='pending' for the %d row(s) above.", len(misclassified))
        return 0

    ids = [sid for sid, _ in misclassified]
    with client.get_session() as session:
        session.execute(
            text("UPDATE sitemaps SET crawl_status = 'pending' WHERE sitemap_id = ANY(:ids)"),
            {"ids": ids},
        )
        session.commit()
    logger.info("Done. %d row(s) corrected rejected_filter -> pending.", len(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
