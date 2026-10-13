import logging

from newscrawler.application.api.crawler_api import FAISS_WRITING_TASKS, CrawlerAPI
from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.network.clients.sqlalchemy_client import (
    SQLAlchemyClient,
)
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def init_crawler():
    sql_alchemy_client = SQLAlchemyClient()
    data_flow_repo = DataFlowRepositoryImpl(sql_alchemy_client)
    chunker = HierarchicalChunker()
    crawler_service = CrawlerServiceImpl(data_flow_repo, chunker=chunker)
    return CrawlerAPI(crawler_service)


def process_event(event, context):
    logger.info(event)
    websites = event.get("website")
    task = event.get("task")

    # OPS-24 (#167): names are validated BEFORE init_crawler(), which loads the
    # models and both FAISS indexes (~2 min, ~4 GB). A typo used to cost the full
    # load before it was rejected.
    if websites:
        websites = [website.strip() for website in websites.split(",")]
        # DBT-12 (#47): validate the list at the dispatch boundary, before any
        # query or crawler lookup. This list comes from the event or the
        # CRAWL_WEBSITES env var, i.e. from a scheduler config -- a typo used to
        # reach load_all_sitemaps, return 0 rows, and only crash later on
        # `NoneType has no batch_crawling_details`, which reads like a quiet
        # source rather than a bad name. Raising here names the offender and, via
        # process_event's re-raise, gives the scheduler a non-zero exit.
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
            validate_website_name,
        )
        websites = [validate_website_name(w) for w in websites]
    else:
        websites = []  # extract_knowledge does not need a website list

    # OPS-38 (#212): task=newsletter takes the day to digest ("date": "YYYY-MM-DD");
    # without one it digests yesterday. Parsed here, before the ~2 min crawler build.
    target_date = None
    if event.get("date"):
        from datetime import date
        target_date = date.fromisoformat(str(event["date"]))
        if task != "newsletter":
            raise ValueError(f"a date only applies to task 'newsletter', not {task!r}")

    # DBT-43 (#183): a manual crawl that embeds must not start while the
    # scheduled crawl holds FAISS: it would load, fetch and embed for hours and
    # then be refused at its flush (OPS-26 while the lock is held, SYS-53's
    # stale-index check after). Refuse before the model load instead. The
    # scheduled run's worker calls crawl_website directly, not through here.
    if task in FAISS_WRITING_TASKS:
        from newscrawler.tools.run_lock import refuse_foreign_writer
        refuse_foreign_writer()

    if task == "newsletter":
        # DBT-74 (#346): the newsletter's own composition root -- no NEWS_L2, no e5-large, no crawlers.
        from newscrawler.application.newsletter_app import build_newsletter_service
        scraper_api = CrawlerAPI(build_newsletter_service())
    else:
        scraper_api = init_crawler()
    try:
        scraper_api.crawl_websites_in_batch(website_names=websites, task=task, target_date=target_date)
    except Exception:
        # SYS-06: this used to catch BaseException, log at INFO, and swallow it,
        # so a scheduler always saw exit 0 no matter what happened. Narrowing to
        # Exception lets KeyboardInterrupt/SystemExit propagate immediately (their
        # normal behaviour), and re-raising after logging makes any other failure
        # both loud in the log and a non-zero exit for __main__.py / the scheduler.
        logger.exception(f"Failed to process task '{task}'")
        raise
