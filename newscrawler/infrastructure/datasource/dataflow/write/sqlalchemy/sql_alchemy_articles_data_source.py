from sqlalchemy import text
import logging
from typing import List, Dict, Tuple

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


class SQLAlchemyArticleDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.client = sql_alchemy_client

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]):
        with self.client.get_session() as session:
            for newsdetail in newsdetails:
                try:
                    entry = NewsArticlesTable(newsdetail)
                    session.add(entry)
                except BaseException as e:
                    logger.error(
                        f"Failed to add sitemap: {newsdetails}\nException: {e}"
                    )

            session.commit()
