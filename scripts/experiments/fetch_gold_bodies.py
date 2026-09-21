#!/usr/bin/env python3
"""
SYS-47 (#143): fetch the body for every headline-only row of the gold set,
through the row's own crawler (the real extractor chain: site selector ->
trafilatura -> newspaper), and store the first 500 chars of the prose --
exactly what the service scores in production (`LEFT(extracted_text, 500)`).

Read-only on the DB (sitemaps.link by sitemap_id). Nothing is saved to
articles/chunks/FAISS: `batch_crawling_details` fetches and extracts, it does
not persist. Output is tests/fixtures/filter_gold_bodies.jsonl, one line per
attempted row: {sitemap_id, source, body_head|null, extractor|null, error|null,
fetched_at}. Resumable: rows already in the output are skipped. Fold the
result into the sample/gold with `scripts/label_filter_gold.py merge-bodies`.

    python scripts/experiments/fetch_gold_bodies.py [--website A,B] [--limit N] [--batch 40]
"""
import argparse
import collections
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.importance_probe import PROBE_BODY_CHARS  # noqa: E402
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
for noisy in ("newscrawler", "trafilatura", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "filter_gold.jsonl")
SAMPLE_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "filter_gold_sample.jsonl")
OUT_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "filter_gold_bodies.jsonl")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def body_head_of(dto) -> str:
    paragraphs = dto.extracted_text if isinstance(dto.extracted_text, list) else [str(dto.extracted_text or "")]
    prose = "\n\n".join(p.strip() for p in paragraphs if p and p.strip())
    return prose[:PROBE_BODY_CHARS]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website", default=None, help="Comma-separated sources (default: every source with headline-only rows)")
    parser.add_argument("--limit", type=int, default=None, help="At most N rows in total (smoke test)")
    parser.add_argument("--batch", type=int, default=40)
    parser.add_argument("--out", default=OUT_PATH)
    args = parser.parse_args(argv)

    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    sample = read_jsonl(SAMPLE_PATH)
    done = {r["sitemap_id"] for r in read_jsonl(args.out)}
    todo = [r for r in sample if not r.get("has_body") and r["sitemap_id"] not in done]
    if args.website:
        keep = {w.strip().upper() for w in args.website.split(",")}
        todo = [r for r in todo if r["source"] in keep]
    todo = [r for r in todo if r["source"] in CRAWLER_DICT]
    if args.limit:
        todo = todo[: args.limit]
    logger.info("%d headline-only rows to fetch (%d already attempted)", len(todo), len(done))
    if not todo:
        return 0

    client = SQLAlchemyClient()
    with client.get_session() as session:
        links = dict(session.execute(
            text("SELECT sitemap_id, link FROM sitemaps WHERE sitemap_id = ANY(:ids)"),
            {"ids": [r["sitemap_id"] for r in todo]},
        ).fetchall())

    by_source = collections.defaultdict(list)
    for r in todo:
        if r["sitemap_id"] in links:
            by_source[r["source"]].append(r)
    stats = collections.Counter()
    with open(args.out, "a", encoding="utf-8", newline="\n") as out:
        for source, rows in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
            crawler = CRAWLER_DICT[source]
            got = failed = 0
            for i in range(0, len(rows), args.batch):
                batch = rows[i:i + args.batch]
                dtos = [SitemapDTO(headline=r["headline"], link=links[r["sitemap_id"]], sources=source,
                                   category=r.get("category"), sitemap_id=r["sitemap_id"]) for r in batch]
                try:
                    result = crawler.batch_crawling_details(news=dtos, website_name=source)
                except Exception as e:  # noqa: BLE001 -- one source must not stop the run
                    logger.error("%s: batch failed: %r", source, e)
                    result, failures = [], {d.sitemap_id: f"batch error: {type(e).__name__}" for d in dtos}
                else:
                    failures = getattr(result, "failures", {}) or {}
                by_id = {d.sitemap_id: d for d in result}
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for r in batch:
                    d = by_id.get(r["sitemap_id"])
                    head = body_head_of(d) if d else ""
                    rec = {"sitemap_id": r["sitemap_id"], "source": source, "fetched_at": now,
                           "body_head": head or None,
                           "extractor": (d.meta_data or {}).get("extractor") if d else None,
                           "error": None if head else (failures.get(r["sitemap_id"]) or "empty extraction")}
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    got += bool(head); failed += not head
                out.flush()
            stats[source] = (got, failed)
            logger.info("%-15s fetched %4d  no body %4d", source, got, failed)
    total_got = sum(g for g, _ in stats.values()); total_failed = sum(f for _, f in stats.values())
    logger.info("done: %d bodies fetched, %d without (%s)", total_got, total_failed, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
