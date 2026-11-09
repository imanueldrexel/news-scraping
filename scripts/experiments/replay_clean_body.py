"""SYS-63 (#204): what the body cleaner would do to bodies already stored. Read-only.

Replays `clean_body_paragraphs` over the articles saved since --since (a sitemaps
`last_crawl_attempt` date) and prints, per source, the share of articles that
carry boilerplate before and after, plus the most frequent lines it removed --
the list to read for any prose it should not have taken.

    venv\\Scripts\\python.exe scripts\\experiments\\replay_clean_body.py --since 2026-10-01
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.utils.utils import clean_body_paragraphs, is_boilerplate_line  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

BACA = re.compile(r"baca juga", re.IGNORECASE)
CHROME = re.compile(r"advertisement|scroll to continue|google news|whatsapp channel|ikuti kami|gulir untuk|\[gambas:",
                    re.IGNORECASE)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", required=True, help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args(argv)

    sql = text("""SELECT s.sources AS source, a.extracted_text AS body
                  FROM articles a JOIN sitemaps s ON s.sitemap_id = a.sitemap_id
                  WHERE s.last_crawl_attempt >= :since""")
    stats = defaultdict(lambda: Counter())
    removed = Counter()
    with SQLAlchemyClient().get_session() as session:
        for row in session.execute(sql, {"since": args.since}):
            body = row.body or ""
            cleaned = clean_body_paragraphs(body)
            c = stats[row.source]
            c["n"] += 1
            c["baca_before"] += bool(BACA.search(body))
            c["baca_after"] += bool(BACA.search(cleaned))
            c["chrome_before"] += bool(CHROME.search(body))
            c["chrome_after"] += bool(CHROME.search(cleaned))
            c["chars_before"] += len(body)
            c["chars_after"] += len(cleaned)
            for line in body.split("\n"):
                if is_boilerplate_line(line):
                    removed[re.sub(r"\d+", "#", line.strip())[:90]] += 1

    print(f"{'source':15s} {'n':>6s} {'baca b/a %':>12s} {'chrome b/a %':>13s} {'chars removed %':>16s}")
    for source, c in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
        n = c["n"]
        print(f"{source:15s} {n:6d} {100*c['baca_before']/n:5.1f}/{100*c['baca_after']/n:<5.1f} "
              f"{100*c['chrome_before']/n:6.1f}/{100*c['chrome_after']/n:<6.1f} "
              f"{100*(c['chars_before']-c['chars_after'])/max(1, c['chars_before']):15.2f}")
    print(f"\nmost frequent removed lines (digits folded to #), top {args.top}:")
    for line, n in removed.most_common(args.top):
        print(f"{n:7d}  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
