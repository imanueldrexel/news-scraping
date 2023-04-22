from sqlalchemy.ext.declarative import declarative_base
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import NewsSitemapModel
from datetime import date
from sqlalchemy import Column, String, BigInteger, Integer, TIMESTAMP, JSON, ForeignKey

from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import NewsDetailsModel

Base = declarative_base()


class SitemapTable(Base):
    __tablename__ = "sitemaps"

    sitemap_id = Column(BigInteger, primary_key=True)
    headline = Column(String)
    link = Column(String)
    sources = Column(String)
    category = Column(String, nullable=True)
    posted_at = Column(TIMESTAMP)
    keywords = Column(JSON, nullable=True)

    def __init__(self, sitemap: NewsSitemapModel):
        self.headline = sitemap.headline
        self.link = sitemap.link
        self.sources = sitemap.sources
        self.category = sitemap.category
        self.posted_at = sitemap.timestamp
        self.keywords = sitemap.keywords


class NewsArticlesTable(Base):
    __tablename__ = "articles"

    articles_id = Column(BigInteger, primary_key=True)
    sitemap_id = Column(Integer, ForeignKey(f"{SitemapTable.__tablename__}.{SitemapTable.sitemap_id.name}"))
    extracted_text = Column(String, nullable=False)
    meta_data = Column(JSON)
    writer = Column(JSON)

    def __init__(self, sitemap: NewsDetailsModel):
        self.sitemap_id = sitemap.sitemap_id
        self.extracted_text = sitemap.extracted_text
        self.writer = sitemap.reporter
        self.meta_data = sitemap.meta_data


# class SourceDictionary(Base):
#     source_id = Column(BigInteger, primary_key=True)
#     source_name = Column(String)
#
#     def __init__(self, source_name: str):
#         self.source_name = source_name
#
#
# class LastCrawlingTime(Base):
#     last_crawling_time_id = Column(BigInteger, primary_key=True)
#     source_id = Column(Integer, ForeignKey(f"{SourceDictionary.__tablename__}.{SourceDictionary.source_id.name}"))
#     latest_crawled_time = Column(TIMESTAMP)
#
#     def __init__(self, source_id: int, latest_crawled_time: date):
#         self.source_id = source_id
#         self.latest_crawled_time = latest_crawled_time
