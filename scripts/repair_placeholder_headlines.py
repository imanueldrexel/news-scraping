#!/usr/bin/env python3
"""
SYS-33 (#114): replace URL-slug placeholder headlines with the page's real title.

SYS-32 stored the URL slug (trailing id included -- "Rupiah Dan Ihsg Menguat
9 September 2026 Ini Pergerakannya Hca5") as `sitemaps.headline` for every
lastmod-only leaf, and the live path never read the page's og:title over it.
The crawler now prefers og:title for a placeholder headline; this script does
the same for the rows written before that fix.

Selection is by the crawler's own test -- `Crawler._is_placeholder_headline`
(headline == what `_derive_headline_from_url(link)` makes of the link) -- over
rows that have already been fetched: those with an `articles` row and those
`rejected_filter` (the rejected ones matter too: their headline is what
SYS-38's re-score and SYS-36's gold set read). `pending` rows are left alone;
the next crawl fixes them on fetch.

Each candidate page is fetched once through its crawler's own `page_loader`
and `Crawler._get_page_title` (og:title, then <title>). A page that yields no
title, or fails to fetch, is reported and left unchanged. Then, in one
transaction after a JSON backup to backups/:
    sitemaps.headline                 -> the page title
    articles.meta_data->>'title'      -> the page title (where an article exists)

Not touched: FAISS docstore `metadata.title` on the saved rows' chunks
(display-only in RAG hits; the SQL side of a hit reads sitemaps.headline).

Usage:
    python scripts/repair_placeholder_headlines.py --dry-run [--website TIRTO,TEMPO] [--limit N]
    python scripts/repair_placeholder_headlines.py [--website TIRTO,TEMPO]
"""
import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(REPO_ROOT, "backups")
DEFAULT_WEBSITES = ("TIRTO", "TEMPO")

_CANDIDATES_SQL = text("""
    SELECT s.sitemap_id, s.sources, s.headline, s.link, s.crawl_status,
           (a.sitemap_id IS NOT NULL) AS has_article, a.meta_data->>'title' AS article_title
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE s.sources = ANY(:websites)
      AND (a.sitemap_id IS NOT NULL OR s.crawl_status = 'rejected_filter')
    ORDER BY s.sitemap_id
""")
_UPDATE_SITEMAP_SQL = text("UPDATE sitemaps SET headline = :h WHERE sitemap_id = :id AND headline IS DISTINCT FROM :h")
_UPDATE_ARTICLE_SQL = text(
    "UPDATE articles SET meta_data = jsonb_set(COALESCE(meta_data, '{}'::jsonb), '{title}', to_jsonb(CAST(:h AS text))) "
    "WHERE sitemap_id = :id AND (meta_data->>'title') IS DISTINCT FROM :h"
)


def find_placeholders(session, websites) -> List:
    """Rows already fetched whose headline is the slug placeholder."""
    rows = session.execute(_CANDIDATES_SQL, {"websites": list(websites)}).fetchall()
    out = []
    for r in rows:
        dto = SitemapDTO(headline=r.headline or "", link=r.link, sources=r.sources, sitemap_id=r.sitemap_id)
        if Crawler._is_placeholder_headline(dto):
            out.append(r)
    return out


def fetch_title(crawler, link: str) -> Tuple[Optional[str], Optional[str]]:
    """(title, error). Uses the crawler's own page loader and title extraction."""
    try:
        soup = crawler.page_loader.get_soup(link)
    except Exception as e:  # noqa: BLE001 -- one bad page must not stop the run
        return None, f"{type(e).__name__}: {e}"[:120]
    if soup is None:
        return None, "no document"
    title = Crawler._get_page_title(soup)
    return (title.strip(), None) if title and title.strip() else (None, "page has no og:title/<title>")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Count, fetch, show a sample; change nothing")
    parser.add_argument("--website", default=",".join(DEFAULT_WEBSITES))
    parser.add_argument("--limit", type=int, default=None, help="Dry-run only: fetch at most N pages for the sample")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    websites = [w.strip().upper() for w in args.website.split(",") if w.strip()]

    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    for w in websites:
        if w not in CRAWLER_DICT:
            raise SystemExit(f"{w}: not a registered crawler")

    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        candidates = find_placeholders(session, websites)

    by_key: Dict[Tuple[str, str, bool], int] = {}
    for r in candidates:
        key = (r.sources, r.crawl_status, bool(r.has_article))
        by_key[key] = by_key.get(key, 0) + 1
    logger.info("%d placeholder-headline row(s) already fetched (articles or rejected_filter)", len(candidates))
    for (source, status, has_article), n in sorted(by_key.items()):
        logger.info("  %-8s %-16s article=%-5s %5d", source, status, has_article, n)
    if not candidates:
        logger.info("Nothing to do.")
        return 0

    to_fetch = candidates[: args.limit] if (args.dry_run and args.limit) else candidates
    logger.info("Fetching og:title for %d page(s) with %d worker(s)...", len(to_fetch), args.workers)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda r: fetch_title(CRAWLER_DICT[r.sources], r.link), to_fetch))

    titles: Dict[int, str] = {}
    failures = []
    for r, (title, err) in zip(to_fetch, results):
        if title:
            titles[r.sitemap_id] = title
        else:
            failures.append((r.sitemap_id, r.sources, err))
    logger.info("%d title(s) read, %d page(s) unchanged (no title / fetch failure)", len(titles), len(failures))
    for sid, src, err in failures[:20]:
        logger.warning("  unchanged sitemap_id=%s %s: %s", sid, src, err)

    sample = [r for r in to_fetch if r.sitemap_id in titles][:8]
    for r in sample:
        logger.info("  %-6s %s\n%14s-> %s", r.sources, r.headline[:80], "", titles[r.sitemap_id][:80])

    if args.dry_run:
        logger.info("[dry-run] Would rewrite %d sitemaps.headline row(s) and %d articles.meta_data title(s).",
                    len(titles), sum(1 for r in to_fetch if r.sitemap_id in titles and r.has_article))
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(BACKUP_DIR, f"sys33_placeholder_headlines_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([{"sitemap_id": r.sitemap_id, "sources": r.sources, "headline": r.headline,
                    "article_title": r.article_title, "new_title": titles.get(r.sitemap_id)}
                   for r in to_fetch], f, default=str, indent=2, ensure_ascii=False)
    logger.info("Backed up %d row(s) to %s", len(to_fetch), backup_path)

    with client.get_session() as session:
        n_sitemaps = n_articles = 0
        for r in to_fetch:
            title = titles.get(r.sitemap_id)
            if not title:
                continue
            n_sitemaps += session.execute(_UPDATE_SITEMAP_SQL, {"id": r.sitemap_id, "h": title}).rowcount
            if r.has_article:
                n_articles += session.execute(_UPDATE_ARTICLE_SQL, {"id": r.sitemap_id, "h": title}).rowcount
        session.commit()
    logger.info("Rewrote %d sitemaps.headline and %d articles.meta_data title(s) in one transaction.", n_sitemaps, n_articles)

    with client.get_session() as session:
        remaining = len(find_placeholders(session, websites))
    logger.info("%d placeholder headline(s) remaining on fetched rows.", remaining)
    return 0


if __name__ == "__main__":
    sys.exit(main())
