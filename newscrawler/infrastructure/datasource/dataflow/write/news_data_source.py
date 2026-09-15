import logging
from typing import List

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.s3repository.s3repository_news_data_source import (
    S3RepositoryNewsDataSource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
    SQLAlchemyArticleDataSource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import (
    SQLAlchemyClient,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NewsDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.s3_repository = S3RepositoryNewsDataSource()
        self.sql_alchemy_sitemap = SQLAlchemySitemapDataSource(sql_alchemy_client)
        self.sql_alchemy_article = SQLAlchemyArticleDataSource(SQLAlchemyClient())

    def save_sitemap(self, sitemaps: List[NewsSitemapModel]) -> List[NewsSitemapModel]:
        saved_articles = []
        if sitemaps:
            for article in sitemaps:
                source = article.sources
                branch = article.category
                try:
                    last_time_crawling = self.sql_alchemy_sitemap.last_time_crawling[
                        source
                    ][branch]
                    delta = article.posted_at - last_time_crawling
                    if delta.days >= 0 and delta.seconds > 0:
                        saved_articles.append(article)
                except KeyError:
                    saved_articles.append(article)
            if saved_articles:
                logger.info(
                    f"get {len(saved_articles)} to scrape for {saved_articles[0].sources}"
                )
                return self.sql_alchemy_sitemap.save_sitemaps(saved_articles)

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]):
        self.sql_alchemy_article.save_newsdetails(newsdetails)

    def mark_sitemaps_attempted(self, sitemap_ids: List[int]):
        self.sql_alchemy_sitemap.mark_sitemaps_attempted(sitemap_ids)

    def load_sitemap(
        self, website: str, n_limit: int
    ) -> List[NewsSitemapModel]:
        return self.sql_alchemy_sitemap.load_all_sitemaps(
            website=website, n_limit=n_limit
        )
