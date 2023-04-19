from datetime import datetime
from sqlalchemy import text
import logging
from typing import List, Dict

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import SitemapTable
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemySitemapDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.client = sql_alchemy_client
        self.last_time_crawling = self.load_last_time_crawling()

    def load_last_time_crawling(self) -> Dict[str, Dict[str, datetime]]:
        last_time_crawling = {}
        with self.client.get_session() as session:
            result = session.execute(text(
                f"SELECT {SitemapTable.sources.name}, {SitemapTable.category.name}, max({SitemapTable.posted_at.name})"
                f"  FROM {SitemapTable.__tablename__}"
                f" GROUP BY {SitemapTable.sources.name}, {SitemapTable.category.name}"))

            for result in result:
                source = result[0]
                category = result[1]
                last_stamped_crawling = result[2]
                try:
                    last_time_crawling[source][category] = last_stamped_crawling
                except KeyError:
                    last_time_crawling[source] = {}
                    last_time_crawling[source][category] = last_stamped_crawling
        return last_time_crawling

    def save(self, sitemaps: List[NewsSitemapModel]):
        with self.client.get_session() as session:
            for sitemap in sitemaps:
                try:
                    entry = SitemapTable(sitemap)
                    session.add(entry)
                except BaseException as e:
                    logger.error(f'Failed to add sitemap: {sitemap.link}\nException: {e}')

            session.commit()
