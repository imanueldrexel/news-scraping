import logging

from newscrawler.application.api.crawler_api import CrawlerAPI
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
    scraper_api = init_crawler()
    websites = event.get("website")
    task = event.get("task")

    if websites:
        websites = [website.strip() for website in websites.split(",")]
    else:
        websites = []  # extract_knowledge does not need a website list

    try:
        scraper_api.crawl_websites_in_batch(website_names=websites, task=task)
    except BaseException as e:
        logger.info(f"Failed to process task '{task}'. Reason: {e}")
