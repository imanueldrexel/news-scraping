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
        # DBT-03 (#22): the injected client, not a second engine and pool.
        self.sql_alchemy_article = SQLAlchemyArticleDataSource(sql_alchemy_client)

    def save_sitemap(self, sitemaps: List[NewsSitemapModel]) -> List[NewsSitemapModel]:
        # No pre-filter here (SYS-07): the old "newer than the last stored posted_at"
        # gate ran before dedup and silently discarded never-seen entries from earlier
        # days -- a missed run could never be backfilled, and date-only sitemaps
        # (EMITENNEWS) lost everything after the first run. save_sitemaps() dedups on
        # link (SYS-29: not (link, posted_at) -- the date is not part of a URL's
        # identity), which is the check that actually matters.
        if not sitemaps:
            return []
        logger.info(f"get {len(sitemaps)} to scrape for {sitemaps[0].sources}")
        return self.sql_alchemy_sitemap.save_sitemaps(sitemaps)

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]) -> List[int]:
        return self.sql_alchemy_article.save_newsdetails(newsdetails)

    def mark_sitemaps_attempted(self, sitemap_ids: List[int]):
        self.sql_alchemy_sitemap.mark_sitemaps_attempted(sitemap_ids)

    def mark_sitemaps_status(self, sitemap_ids: List[int], status: str):
        self.sql_alchemy_sitemap.mark_sitemaps_status(sitemap_ids, status)

    def increment_fetch_failures(self, sitemap_ids: List[int], error_msg: str = None):
        self.sql_alchemy_sitemap.increment_fetch_failures(sitemap_ids, error_msg)

    def get_saved_category_pairs(self, website: str):
        return self.sql_alchemy_sitemap.get_saved_category_pairs(website)

    def terminal_with_chunks(self, website: str):
        return self.sql_alchemy_sitemap.terminal_with_chunks(website)

    def update_sitemap_headlines(self, headlines_by_id) -> int:
        return self.sql_alchemy_sitemap.update_headlines(headlines_by_id)

    def load_sitemap(
        self, website: str, n_limit: int
    ) -> List[NewsSitemapModel]:
        return self.sql_alchemy_sitemap.load_all_sitemaps(
            website=website, n_limit=n_limit
        )
