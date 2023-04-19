import logging

from newscrawler.application.api.crawler_api import CrawlerAPI
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import (
    DataFlowRepositoryImpl,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def init_crawler():
    sql_alchemy_client = SQLAlchemyClient()
    data_flow_repo = DataFlowRepositoryImpl(NewsDataSource(sql_alchemy_client))
    crawler_service = CrawlerServiceImpl(data_flow_repo)

    return CrawlerAPI(crawler_service)


def process_event(event, context):
    logger.info(event)
    scraper_api = init_crawler()
    websites = event.get("website")
    if websites:
        websites = [website.strip() for website in websites.split(",")]
        try:
            scraper_api.crawl_website_in_batch(websites)
        except BaseException as e:
            logger.info(f"Failed to crawl. Reason: {e}")
