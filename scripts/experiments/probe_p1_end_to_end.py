#!/usr/bin/env python3
"""
QA probe: run one small, real full_text crawl through the production stack and
check five closed P1 fixes against what actually landed in the live DB.

  SYS-04 (#5)  crawl_log.article_count is the real saved count, not 0
  SYS-16 (#37) filtered-out sitemaps get a terminal crawl_status
  SYS-17 (#38) every saved article ends up with chunks rows (L1 and L2)
  SYS-18 (#39) articles.extracted_text is prose, not a Postgres array literal
  OPS-02 (#10) articles.meta_data->>'extractor' records which extractor won

Uses the real CrawlerServiceImpl with a small limit so only a handful of articles
are fetched and saved.

    python scripts/experiments/probe_p1_end_to_end.py --website IDXCHANNEL --limit 6
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text

from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)


def snapshot(session, website):
    q = lambda sql: session.execute(text(sql), {"w": website}).fetchone()  # noqa: E731
    return {
        "articles": q("SELECT COUNT(*) FROM articles a JOIN sitemaps s ON s.sitemap_id=a.sitemap_id WHERE s.sources=:w")[0],
        "status": dict(session.execute(
            text("SELECT crawl_status, COUNT(*) FROM sitemaps WHERE sources=:w GROUP BY 1"), {"w": website}).fetchall()),
        "max_log": q("SELECT COALESCE(MAX(log_id),0) FROM crawl_log")[0],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--website", default="IDXCHANNEL")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--sitemap-first", action="store_true",
                    help="Run crawl_sitemaps first so the full_text queue contains today's never-tried URLs")
    args = ap.parse_args()

    client = SQLAlchemyClient()
    with client.get_session() as s:
        before = snapshot(s, args.website)
    print(f"BEFORE {args.website}: {before}")

    repo = DataFlowRepositoryImpl(client)
    service = CrawlerServiceImpl(repo, chunker=HierarchicalChunker(), limit=args.limit)
    if args.sitemap_first:
        service.crawl_sitemaps(website_name=args.website)
    service.crawl_newsdetails(website_name=args.website)

    with client.get_session() as s:
        after = snapshot(s, args.website)
        print(f"AFTER  {args.website}: {after}")

        rows = s.execute(text(
            "SELECT log_id, task, status, article_count FROM crawl_log "
            "WHERE log_id > :m AND website = :w ORDER BY log_id"), {"m": before["max_log"], "w": args.website}).fetchall()
        print("\n--- SYS-04: new crawl_log rows ---")
        for r in rows:
            print(f"  log_id={r.log_id} task={r.task} status={r.status} article_count={r.article_count}")

        print("\n--- SYS-16: crawl_status transitions ---")
        for k in ("pending", "rejected_filter", "empty_extraction", "saved"):
            b, a = before["status"].get(k, 0), after["status"].get(k, 0)
            if b != a:
                print(f"  {k}: {b} -> {a}  ({a - b:+d})")

        new_arts = s.execute(text("""
            SELECT a.articles_id, a.sitemap_id, LENGTH(a.extracted_text) AS len,
                   LEFT(a.extracted_text, 60) AS head,
                   a.meta_data->>'extractor' AS extractor,
                   a.writer::text AS writer,
                   (SELECT COUNT(*) FROM chunks c WHERE c.sitemap_id=a.sitemap_id AND c.chunk_level=1) AS l1,
                   (SELECT COUNT(*) FROM chunks c WHERE c.sitemap_id=a.sitemap_id AND c.chunk_level=2) AS l2
            FROM articles a JOIN sitemaps s ON s.sitemap_id=a.sitemap_id
            WHERE s.sources=:w ORDER BY a.articles_id DESC LIMIT :n
        """), {"w": args.website, "n": max(1, after["articles"] - before["articles"])}).fetchall()

        print("\n--- SYS-17 / SYS-18 / OPS-02: the rows just written ---")
        for r in new_arts:
            flag = "ARRAY-LITERAL!" if r.head.startswith('{"') else "prose"
            print(f"  art={r.articles_id} sitemap={r.sitemap_id} len={r.len} {flag} "
                  f"extractor={r.extractor!r} L1={r.l1} L2={r.l2} writer={(r.writer or '')[:40]}")
            print(f"      head: {r.head!r}")


if __name__ == "__main__":
    main()
