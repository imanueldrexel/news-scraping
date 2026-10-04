"""Generate a newsletter preview without writing to the database.

Reads the day's articles, clusters and summarizes them exactly as `task=newsletter`
does (same generator, same summarizer), but `save_digest` is a no-op and the
summaries are not counted in api_usage_log, so nothing is written to Postgres.
The markdown goes to --out-dir (default digests/preview), not digests/.

    venv\\Scripts\\python.exe scripts\\preview_newsletter.py --date 2026-10-03

SYS-67 (#215) / SYS-68 (#216): the tool for looking at what a clustering or
summarizer change does to a real day. It reads Postgres and the MiniLM model;
it does not touch the FAISS indexes, so it needs no run lock.
"""
import argparse
import logging
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import newscrawler.core.newsletter_generator as newsletter_generator  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (  # noqa: E402,E501
    SQLAlchemyNewsletterDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

logger = logging.getLogger("preview_newsletter")


class ReadOnlyNewsletterDataSource(SQLAlchemyNewsletterDataSource):
    """The real reads; `save_digest` only reports what it would have stored."""

    def save_digest(self, digest_date, file_path, cluster_count, article_count, categories, source_ids,
                    generation_ms):
        logger.info("preview: would store %s (%d clusters, %d articles) categories=%s",
                    file_path, cluster_count, article_count, categories.get(newsletter_generator.SUMMARIES_KEY))
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, the articles' publication day")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "digests", "preview"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    newsletter_generator.DIGESTS_DIR = args.out_dir
    generator = newsletter_generator.NewsletterGenerator(ReadOnlyNewsletterDataSource(SQLAlchemyClient()))
    path = generator.generate(date.fromisoformat(args.date))
    print(path)
    if getattr(path, "note", None):
        print(f"NOTE: {path.note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
