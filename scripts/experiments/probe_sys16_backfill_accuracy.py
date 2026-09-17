#!/usr/bin/env python3
"""
QA probe (SYS-16, #37): how often does the headline-only backfill classification
disagree with the decision the real pipeline would have made?

scripts/backfill_sitemap_crawl_status.py marked 24,963 sitemaps 'rejected_filter'
-- a PERMANENT exclusion from load_all_sitemaps -- using
SemanticImportanceFilter.is_important(headline). The live pipeline instead calls
is_important(title + " " + body[:500]). Those are different inputs, so the
backfill's accuracy is an open question that was never measured before the rows
were written.

Method: sample rows marked 'rejected_filter', fetch each article through the real
crawler (_get_news_details, same code path the pipeline uses), then score both
ways and count the disagreements. A disagreement where body-aware says "important"
is a false positive -- an article the pipeline would have kept, now permanently
excluded.

    python scripts/experiments/probe_sys16_backfill_accuracy.py --sample 40
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text

from newscrawler.core.constants import INTERESTS
from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.importance_filter import SemanticImportanceFilter
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

SQL = text("""
    SELECT sitemap_id, headline, link, sources, category, posted_at
    FROM sitemaps
    WHERE crawl_status = 'rejected_filter' AND sources = ANY(:sources)
    ORDER BY md5(sitemap_id::text)
    LIMIT :limit
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--sources", default="KOMPAS,CNBC,IDXCHANNEL,JPNN,TVONENEWS,SINDONEWS")
    args = ap.parse_args()
    sources = [s.strip() for s in args.sources.split(",")]

    client = SQLAlchemyClient()
    with client.get_session() as session:
        rows = session.execute(SQL, {"sources": sources, "limit": args.sample}).fetchall()
    print(f"sampled {len(rows)} rows marked rejected_filter from {sources}")

    filt = SemanticImportanceFilter(interests=INTERESTS, model_name="paraphrase-multilingual-MiniLM-L12-v2")

    agree_reject = disagree = fetch_failed = 0
    false_positives = []
    for r in rows:
        crawler = CRAWLER_DICT.get(r.sources)
        dto = SitemapDTO(
            headline=r.headline, link=r.link, sources=r.sources, category=r.category,
            timestamp=datetime.strptime(str(r.posted_at), "%Y%m%d"), keywords=None,
            sitemap_id=r.sitemap_id,
        )
        try:
            detail = crawler._get_news_details(dto)
        except Exception as e:  # noqa: BLE001
            print(f"  [{r.sitemap_id}] fetch raised {type(e).__name__}: {e}")
            fetch_failed += 1
            continue
        body = " ".join(detail.extracted_text) if detail and detail.extracted_text else ""
        if not body.strip():
            fetch_failed += 1
            continue

        headline_says = filt.is_important(r.headline or "")
        pipeline_says = filt.is_important(f"{r.headline} {body[:500]}")
        if pipeline_says and not headline_says:
            disagree += 1
            false_positives.append((r.sitemap_id, r.sources, (r.headline or "")[:70]))
        else:
            agree_reject += 1

    checked = agree_reject + disagree
    print(f"\nfetched+scored: {checked}  (fetch failed / empty body: {fetch_failed})")
    if checked:
        print(f"headline-only and body-aware AGREE (reject):     {agree_reject} ({agree_reject/checked:.0%})")
        print(f"DISAGREE -- body-aware would have KEPT the article: {disagree} ({disagree/checked:.0%})")
    for sid, src, h in false_positives:
        print(f"   FALSE POSITIVE sitemap_id={sid} {src}: {h}")


if __name__ == "__main__":
    main()
