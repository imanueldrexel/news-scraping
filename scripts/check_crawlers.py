#!/usr/bin/env python3
"""
Crawler health checker -- sample-crawls every outlet in CRAWLER_DICT and reports which
crawlers are broken (sitemap listing parse OR article-body extraction).

Per outlet it runs the REAL production code paths on a tiny sample:
  Stage A (listing): get_soup(website_url) -> _get_branches -> _scrape(first branch)
  Stage B (article): batch_crawling_sitemap -> batch_crawling_details, check extracted_text

Status:
  OK      listing returned links AND >=1 sample article extracted non-empty text
  PARTIAL listing OK but 0 sample articles produced text (body extraction broken)
  BROKEN  sitemap fetch/parse/listing failed
  ERROR   unexpected exception (message captured)

Usage:
    python scripts/check_crawlers.py
    python scripts/check_crawlers.py --website KOMPAS,DETIK --sample-size 2
    python scripts/check_crawlers.py --json
    python scripts/check_crawlers.py --quiet --log-db

Exit code: 0 = all healthy, 1 = one or more outlets BROKEN/PARTIAL/ERROR.

Daily cron (Linux):
    0 6 * * * cd /path/to/news-scraping && venv/bin/python scripts/check_crawlers.py >> crawler_health/cron.log 2>&1
Windows Task Scheduler: daily trigger; action = <repo>\\venv\\Scripts\\python.exe scripts\\check_crawlers.py ; start-in = repo root.
"""
import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
# Silence the chatty per-branch crawler logs during checking.
logging.getLogger("newscrawler.infrastructure.datasource.scrapers.crawler").setLevel(logging.ERROR)
logger = logging.getLogger("check_crawlers")

from newscrawler.core.crawler_dict_list import CRAWLER_DICT

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_BROKEN = "BROKEN"
STATUS_ERROR = "ERROR"
UNHEALTHY = {STATUS_PARTIAL, STATUS_BROKEN, STATUS_ERROR}


def _extracted_len(detail) -> int:
    txt = getattr(detail, "extracted_text", None)
    if not txt:
        return 0
    if isinstance(txt, list):
        return sum(len(str(p)) for p in txt)
    return len(str(txt))


def classify(sitemap_links: int, detail_ok: int, error: bool = False) -> str:
    """Pure classification from sample-crawl counts."""
    if error:
        return STATUS_ERROR
    if sitemap_links <= 0:
        return STATUS_BROKEN
    if detail_ok <= 0:
        return STATUS_PARTIAL
    return STATUS_OK


def check_one(name: str, crawler, sample_size: int) -> dict:
    """Sample-crawl one outlet using the real code paths. Never raises."""
    result = {
        "website": name, "sitemap_links": 0, "dto_count": 0,
        "detail_total": 0, "detail_ok": 0, "avg_chars": 0,
        "status": STATUS_BROKEN, "note": "",
    }
    try:
        soup = crawler.page_loader.get_soup(crawler.website_url)
        if not soup:
            result["note"] = "sitemap fetch failed (get_soup returned None)"
            return result
        branches = crawler._get_branches(soup) or {}
        if not branches:
            result["note"] = "no branches parsed from sitemap"
            return result

        first_name, first_link = next(iter(branches.items()))
        articles = crawler._scrape(branch_link=first_link, branch_name=first_name) or []
        result["sitemap_links"] = len(articles)
        if not articles:
            result["note"] = "first branch scraped 0 article links"
            return result

        dtos = crawler.batch_crawling_sitemap(articles[:sample_size], name) or []
        result["dto_count"] = len(dtos)
        if not dtos:
            result["status"] = STATUS_PARTIAL
            result["note"] = "links found but SitemapDTO validation produced none"
            return result

        # Sample DTOs from a fresh scrape have sitemap_id=None; _get_news_details builds a
        # NewsDetailsDTO(sitemap_id=...) which requires an int. Stamp a placeholder id so the
        # check exercises real article extraction instead of failing validation first.
        # Use object.__setattr__ to bypass the frozen dataclass + pydantic re-validation
        # (dataclasses.replace would re-validate and choke on optional fields like timestamp).
        sample = list(dtos[:sample_size])
        for d in sample:
            try:
                object.__setattr__(d, "sitemap_id", 0)
            except Exception:
                pass
        details = crawler.batch_crawling_details(sample, name) or []
        result["detail_total"] = len(sample)
        lengths = [_extracted_len(d) for d in details]
        ok = [l for l in lengths if l > 0]
        result["detail_ok"] = len(ok)
        result["avg_chars"] = int(sum(ok) / len(ok)) if ok else 0
        result["status"] = classify(result["sitemap_links"], result["detail_ok"])
        if result["status"] == STATUS_PARTIAL:
            result["note"] = "listing OK but article body extraction returned empty"
        return result
    except Exception as e:
        result["status"] = STATUS_ERROR
        result["note"] = ("%s: %s" % (type(e).__name__, e))[:200]
        return result


def run_checks(targets: dict, sample_size: int, workers: int, timeout: int) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {
            ex.submit(check_one, name, crawler, sample_size): name
            for name, crawler in targets.items()
        }
        for fut, name in future_map.items():
            try:
                results.append(fut.result(timeout=timeout))
            except FutureTimeout:
                results.append({
                    "website": name, "sitemap_links": 0, "dto_count": 0,
                    "detail_total": 0, "detail_ok": 0, "avg_chars": 0,
                    "status": STATUS_ERROR, "note": "timeout after %ds" % timeout,
                })
    order = {STATUS_BROKEN: 0, STATUS_ERROR: 1, STATUS_PARTIAL: 2, STATUS_OK: 3}
    results.sort(key=lambda r: (order.get(r["status"], 9), r["website"]))
    return results


def render_table(results: list) -> str:
    rows = ["%-14s %-8s %-6s %-5s %-15s %s" % (
        "SOURCE", "STATUS", "LINKS", "DTOs", "DETAIL(ok/tot)", "NOTE"),
        "-" * 100]
    for r in results:
        detail = "%d/%d (%dch)" % (r["detail_ok"], r["detail_total"], r["avg_chars"])
        rows.append("%-14s %-8s %-6d %-5d %-15s %s" % (
            r["website"][:14], r["status"], r["sitemap_links"],
            r["dto_count"], detail, r["note"][:60]))
    return "\n".join(rows)


def summary_line(results: list) -> str:
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    unhealthy = [r["website"] for r in results if r["status"] in UNHEALTHY]
    parts = ["%s=%d" % (s, counts.get(s, 0)) for s in
             (STATUS_OK, STATUS_PARTIAL, STATUS_BROKEN, STATUS_ERROR)]
    line = "Crawler health: " + ", ".join(parts) + " (of %d)" % len(results)
    if unhealthy:
        line += " | needs attention: " + ", ".join(unhealthy)
    return line


def write_report(results: list, report_dir: str) -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, datetime.now().strftime("%Y-%m-%d") + ".json")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "unhealthy": [r["website"] for r in results if r["status"] in UNHEALTHY],
        "results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def log_to_db(results: list) -> None:
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    # crawl_log.status CHECK allows only started/completed/failed.
    with client.get_session() as session:
        for r in results:
            db_status = "completed" if r["status"] == STATUS_OK else "failed"
            note = ("%s: %s" % (r["status"], r["note"])) if r["note"] else r["status"]
            session.execute(text(
                "INSERT INTO crawl_log (website, task, status, article_count, error_msg, finished_at) "
                "VALUES (:w, 'health_check', :s, :c, :e, NOW())"
            ), {"w": r["website"], "s": db_status, "c": r["sitemap_links"], "e": note})
        session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawler health checker")
    parser.add_argument("--website", help="Comma-separated subset (default: all)")
    parser.add_argument("--sample-size", type=int, default=3, help="Sample articles per outlet (default 3)")
    parser.add_argument("--workers", type=int, default=8, help="Outlet-level parallelism (default 8)")
    parser.add_argument("--timeout", type=int, default=60, help="Per-outlet timeout seconds (default 60)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout")
    parser.add_argument("--quiet", action="store_true", help="Print only the one-line summary")
    parser.add_argument("--report-dir", default="crawler_health", help="Where to write the dated JSON report")
    parser.add_argument("--log-db", action="store_true", help="Also append one crawl_log row per outlet")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.website:
        wanted = [w.strip().upper() for w in args.website.split(",") if w.strip()]
        targets = {n: c for n, c in CRAWLER_DICT.items() if n.upper() in wanted}
        missing = [w for w in wanted if w not in {n.upper() for n in CRAWLER_DICT}]
        if missing:
            print("Unknown outlet(s): %s" % ", ".join(missing), file=sys.stderr)
        if not targets:
            print("No matching outlets.", file=sys.stderr)
            return 1
    else:
        targets = dict(CRAWLER_DICT)

    results = run_checks(targets, args.sample_size, args.workers, args.timeout)

    report_path = write_report(results, args.report_dir)
    if args.log_db:
        try:
            log_to_db(results)
        except Exception as e:
            print("WARN: --log-db failed: %s" % e, file=sys.stderr)

    if args.json:
        print(json.dumps({"results": results,
                          "unhealthy": [r["website"] for r in results if r["status"] in UNHEALTHY]},
                         ensure_ascii=False, indent=2))
    elif args.quiet:
        print(summary_line(results))
    else:
        print(render_table(results))
        print()
        print(summary_line(results))
        print("Report written to %s" % report_path)

    return 1 if any(r["status"] in UNHEALTHY for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
