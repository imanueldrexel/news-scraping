from datetime import datetime, timezone, timedelta
from sqlalchemy import text
import logging
from typing import List, Dict, Tuple

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import (
    SitemapTable,
    NewsArticlesTable,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import (
    SQLAlchemyClient,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemySitemapDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.client = sql_alchemy_client
        self.last_time_crawling = self.load_last_time_crawling()

    def load_last_time_crawling(self) -> Dict[str, Dict[str, datetime]]:
        last_time_crawling = {}
        with self.client.get_session() as session:
            result = session.execute(
                text(
                    f"SELECT {SitemapTable.sources.name}, {SitemapTable.category.name}, max({SitemapTable.posted_at.name})"
                    f"  FROM {SitemapTable.__tablename__}"
                    f" GROUP BY {SitemapTable.sources.name}, {SitemapTable.category.name}"
                )
            )

            for result in result:
                source = result[0]
                category = result[1]
                last_stamped_crawling: datetime = result[2]
                try:
                    last_time_crawling[source][category] = (
                        last_stamped_crawling.replace(
                            tzinfo=timezone(timedelta(hours=0))
                        )
                    )
                except KeyError:
                    last_time_crawling[source] = {}
                    last_time_crawling[source][category] = (
                        last_stamped_crawling.replace(
                            tzinfo=timezone(timedelta(hours=0))
                        )
                    )
        return last_time_crawling

    def save_sitemaps(self, sitemaps: List[NewsSitemapModel]):
        with self.client.get_session() as session:
            # Query the latest sitemap_id from the database
            latest_sitemap = (
                session.query(SitemapTable)
                .order_by(SitemapTable.sitemap_id.desc())
                .first()
            )
            latest_sitemap_id = latest_sitemap.sitemap_id if latest_sitemap else 0

            for sitemap in sitemaps:
                try:
                    # Increment the sitemap_id
                    new_sitemap_id = latest_sitemap_id + 1
                    entry = SitemapTable(sitemap)
                    entry.sitemap_id = new_sitemap_id
                    latest_sitemap_id = new_sitemap_id  # Update the latest_sitemap_id for the next iteration

                    session.add(entry)
                except BaseException as e:
                    logger.error(
                        f"Failed to add sitemap: {sitemap.link}\nException: {e}"
                    )

            session.commit()

    def load_all_sitemaps(
        self, website: str, n_limit: int
    ) -> Dict[str, List[Tuple[int, str]]]:
        website = f"'{website}'"
        target_news = {}
        with self.client.get_session() as session:
            result = session.execute(
                text(
                    f"SELECT a.{SitemapTable.sources.name}, a.{SitemapTable.link.name}, a.{SitemapTable.sitemap_id.name}"
                    f"  FROM {SitemapTable.__tablename__} as a"
                    f"       LEFT JOIN (SELECT {NewsArticlesTable.sitemap_id.name} "
                    f"                    FROM {NewsArticlesTable.__tablename__}"
                    f"                 ) as b"
                    f"       ON a.{SitemapTable.sitemap_id.name} = b.{NewsArticlesTable.sitemap_id.name}"
                    f" WHERE {SitemapTable.sources.name} in ({website})"
                    f"   AND b.{NewsArticlesTable.sitemap_id.name} is NULL"
                    f" LIMIT {n_limit}"
                )
            )

            for result in result:
                source = result[0]
                link = result[1]
                id = result[2]
                try:
                    target_news[source].append((id, link))
                except KeyError:
                    target_news[source] = [(id, link)]
        return target_news
