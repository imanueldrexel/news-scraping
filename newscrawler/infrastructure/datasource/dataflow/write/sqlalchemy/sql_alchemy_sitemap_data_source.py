from datetime import datetime
from sqlalchemy import text
import logging
from typing import List, Dict, Tuple

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import SitemapTable, NewsArticlesTable
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

    def save_sitemaps(self, sitemaps: List[NewsSitemapModel]):
        with self.client.get_session() as session:
            for sitemap in sitemaps:
                try:
                    entry = SitemapTable(sitemap)
                    session.add(entry)
                except BaseException as e:
                    logger.error(f'Failed to add sitemap: {sitemap.link}\nException: {e}')

            session.commit()

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]):
        with self.client.get_session() as session:
            for newsdetail in newsdetails:
                try:
                    entry = NewsArticlesTable(newsdetail)
                    session.add(entry)
                except BaseException as e:
                    logger.error(f'Failed to add sitemap: {newsdetails}\nException: {e}')

            session.commit()

    def load_target_news(self, target_sitemaps_id: List[int]) -> Dict[str, List[Tuple[int, str]]]:
        target_news = {}
        target_sitemaps_id = ", ".join([str(x) for x in target_sitemaps_id])
        with self.client.get_session() as session:
            result = session.execute(text(
                f"SELECT {SitemapTable.sources.name}, {SitemapTable.link.name}, {SitemapTable.sitemap_id.name}"
                f"  FROM {SitemapTable.__tablename__}"
                f" WHERE {SitemapTable.sitemap_id.name} in ({target_sitemaps_id})"))

            for result in result:
                source = result[0]
                link = result[1]
                id = result[2]
                try:
                    target_news[source].append((id, link))
                except KeyError:
                    target_news[source] = [(id, link)]

        return target_news
