"""SYS-50 (#165): how big is each scheduled source's article queue once the
category-denied rows no longer cost a fetch?

Read-only. Eligibility is `load_all_sitemaps`' own predicate (no `articles` row,
not `rejected_filter`, past the cooldown, under the fetch-failure cap). The deny
decision is the live one, `category_gate(category, source)`, per (source,
category). Sources are the OPS-19 schedule (`HEALTHY` minus `DEFAULT_EXCLUDED`).

    venv\\Scripts\\python.exe scripts/experiments/probe_queue_net_of_denied.py
"""
import importlib.util
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import SITEMAP_MAX_FETCH_FAILURES, SITEMAP_RECRAWL_COOLDOWN_DAYS  # noqa: E402
from newscrawler.core.importance_filter import category_gate  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

_SQL = text("""
    SELECT s.sources, s.category, COUNT(*) AS n
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
    WHERE a.sitemap_id IS NULL AND s.crawl_status != 'rejected_filter'
      AND (s.last_crawl_attempt IS NULL OR s.last_crawl_attempt < NOW() - make_interval(days => :cooldown))
      AND s.fetch_failures < :max_ff AND s.sources = ANY(:sources)
    GROUP BY 1, 2
""")


def _schedule():
    spec = importlib.util.spec_from_file_location("rsc", os.path.join(ROOT, "scripts", "run_scheduled_crawl.py"))
    rsc = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, ["run_scheduled_crawl.py"]
    try:
        spec.loader.exec_module(rsc)
    finally:
        sys.argv = saved
    return rsc._scheduled_sources(rsc._healthy_list())[0]


def main():
    sources = _schedule()
    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(_SQL, {"cooldown": SITEMAP_RECRAWL_COOLDOWN_DAYS, "max_ff": SITEMAP_MAX_FETCH_FAILURES,
                                "sources": sources}).fetchall()
    per = {}
    for r in rows:
        e, d = per.get(r.sources, (0, 0))
        per[r.sources] = (e + r.n, d + (r.n if category_gate(r.category, r.sources) == "deny" else 0))
    print("%-16s %9s %7s %6s %11s %12s" % ("source", "eligible", "denied", "%", "net queue", "net per run"))
    te = td = 0
    for src in sorted(per, key=lambda k: -per[k][1]):
        e, d = per[src]
        te, td = te + e, td + d
        print("%-16s %9d %7d %5.0f%% %11d %12d" % (src, e, d, 100.0 * d / e if e else 0, e - d, min(e - d, 1000)))
    print("%-16s %9d %7d %5.0f%% %11d" % ("ALL (%d)" % len(sources), te, td, 100.0 * td / te if te else 0, te - td))


if __name__ == "__main__":
    sys.exit(main())
