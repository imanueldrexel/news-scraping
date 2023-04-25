import logging
from typing import List, Dict, Tuple

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel
from newscrawler.infrastructure.datasource.dataflow.write.s3repository.s3repository_news_data_source import (
    S3RepositoryNewsDataSource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import \
    SQLAlchemySitemapDataSource
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NewsDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.s3_repository = S3RepositoryNewsDataSource()
        self.sql_alchemy_sitemap = SQLAlchemySitemapDataSource(sql_alchemy_client)

    def save_sitemap(self, sitemaps: List[NewsSitemapModel]):
        saved_articles = []
        if sitemaps:
            # source = articles[0].sources
            # logger.info("Saving to S3...")
            # date_now = str(datetime.datetime.utcnow()).split(".")[0]
            # date_now = re.sub(r"([\s:,-])", r"_", date_now)
            # key_name = f"{date_now}"
            # article_dict = []
            # for article in articles:
            #     article_dict.append(article.to_dict())
            # self.s3_repository.save(
            #     key=key_name, batch_results=article_dict, news_source=source
            # )
            for article in sitemaps:
                source = article.sources
                branch = article.category
                try:
                    last_time_crawling = self.sql_alchemy_sitemap.last_time_crawling[source][branch]
                    delta = article.timestamp - last_time_crawling.astimezone(article.timestamp.tzinfo)
                    if delta.days >= 0 and delta.seconds > 0:
                        saved_articles.append(article)
                except KeyError:
                    saved_articles.append(article)
            logger.info(f"get {len(saved_articles)} to scrape for {article.sources[0]}")
            self.sql_alchemy_sitemap.save_sitemaps(saved_articles)

    def save_newsdetails(self, newsdetails: List[NewsDetailsModel]):
        if newsdetails:
            self.sql_alchemy_sitemap.save_newsdetails(newsdetails)

    def load_target_news(self, target_sitemaps_id: List[int]) -> Dict[str, List[Tuple[int, str]]]:
        return self.sql_alchemy_sitemap.load_target_news(target_sitemaps_id)