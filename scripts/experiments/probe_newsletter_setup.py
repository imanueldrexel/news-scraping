"""DBT-74 (#346) / SYS-147 (#337): what the newsletter's composition root costs, and the story arcs'
timelines on a real day. Read-only: SELECTs, NEWS_L1 (and with --path old NEWS_L2) loaded, never saved;
no LLM call (the digest is built without a summarizer); the digest goes to --out-dir and
`save_digest` only reports.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_newsletter_setup.py --path new --date 2026-10-12 ^
        --out-dir digests\\preview\\dbt74 --arcs digests\\2026-10-12-ringkas.md
    venv\\Scripts\\python.exe scripts\\experiments\\probe_newsletter_setup.py --path old --date 2026-10-12 ^
        --out-dir digests\\preview\\dbt74-old

--path new: build_newsletter_service() (MiniLM + NEWS_L1 read-only). --path old: init_crawler() (the
whole crawler: NEWS_L1 + NEWS_L2 + e5-large + crawlers), what the 12:00 job used before DBT-74.
Prints one JSON line: build seconds, RSS after the build (GB), peak RSS, digest seconds, digest sha256.
--arcs EDITION: for each Berita Utama lead of that edition, the thread_finder timeline (new path only).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


class Peak:
    """Samples this process's RSS every 0.2 s."""

    def __init__(self):
        import psutil
        self.proc, self.peak, self.stop = psutil.Process(), 0, False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop:
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(0.2)

    def now(self):
        return self.proc.memory_info().rss


def gb(n):
    return round(n / 1024 ** 3, 2)


def leads(edition_path):
    out = []
    for line in open(edition_path, encoding="utf-8"):
        m = re.match(r"### \[(.+?)\]\((\S+?)\)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def arcs(service, edition_path, day):
    """Each lead's timeline through the service's own search and the real lookup."""
    from sqlalchemy import text

    from newscrawler.core.thread_finder import find_thread
    gen = service.generator
    rows = []
    with gen.ds.client.get_session() as s:
        for title, link in leads(edition_path):
            bare = link.split("?page=all")[0]
            r = s.execute(text("SELECT s.sitemap_id, c.text_content FROM sitemaps s JOIN chunks c ON "
                               "c.sitemap_id = s.sitemap_id AND c.chunk_level = 1 WHERE s.link IN (:a, :b)"),
                          {"a": bare, "b": link}).fetchone()
            rows.append((title, r))
    for title, r in rows:
        if r is None:
            print(json.dumps({"lead": title, "error": "not found"}, ensure_ascii=False))
            continue
        vector = gen._encode([r.text_content])[0]
        items = find_thread(vector, day, [r.sitemap_id], gen._search_l1, gen.ds.get_timeline_rows)
        print(json.dumps({"lead": title, "items": len(items),
                          "timeline": [f"{i.day} {i.cosine:.3f} [{i.day_volume}] {i.source}: {i.headline[:70]}"
                                       for i in items]}, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", choices=("new", "old"), required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--arcs")
    a = ap.parse_args(argv)
    day = date.fromisoformat(a.date)
    peak = Peak()
    base = peak.now()
    t0 = time.time()
    if a.path == "new":
        from newscrawler.application.newsletter_app import build_newsletter_service
        service = build_newsletter_service()
        generator = service.generator
    else:
        from newscrawler.application.api.lambda_function.lambda_handler import init_crawler
        api = init_crawler()
        service = None
        generator = api.crawler_service.data_flow_repo.newsletter_generator
    built_s, built_rss = round(time.time() - t0, 1), peak.now()

    import newscrawler.core.newsletter_generator as ng
    ng.DIGESTS_DIR = a.out_dir
    generator._summarizer = None                     # no LLM call: headline lists, no edition
    generator.ds.save_digest = lambda **kw: 0        # read-only
    t1 = time.time()
    path = generator.generate(day)
    digest_s = round(time.time() - t1, 1)
    digest = open(str(path), "rb").read()
    peak.stop = True
    print(json.dumps({"path": a.path, "date": a.date, "build_s": built_s, "rss_before_gb": gb(base),
                      "rss_after_build_gb": gb(built_rss), "peak_rss_gb": gb(peak.peak), "digest_s": digest_s,
                      "digest_sha256": hashlib.sha256(digest).hexdigest()[:16], "digest": str(path)}))
    if a.arcs and service is not None:
        arcs(service, a.arcs, day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
