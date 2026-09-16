from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from dataclasses import replace
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
from newscrawler.core.constants import SITEMAP_RECRAWL_COOLDOWN_DAYS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemySitemapDataSource:
    def __init__(self, sql_alchemy_client: SQLAlchemyClient):
        self.client = sql_alchemy_client

    def load_last_time_crawling(self) -> Dict[str, Dict[str, datetime]]:
        """Max posted_at per (source, category). No longer used by the crawl path
        (the pre-dedup date gate was removed in SYS-07); kept for ad-hoc tooling."""
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
                last_stamped_crawling = datetime.strptime(str(result[2]), "%Y%m%d").replace(tzinfo=timezone(timedelta(hours=7)))
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

    def save_sitemaps(self, sitemaps: List[NewsSitemapModel]) -> List[NewsSitemapModel]:
        if not sitemaps:
            return []

        # This will hold our new, updated objects
        updated_sitemaps_list = []

        with self.client.get_session() as session:
            # 1. Pre-fetch existing data (Optimization)
            posted_dates = [
                int(s.posted_at.strftime("%Y%m%d")) 
                for s in sitemaps if s.posted_at
            ]
            earliest_posted_at = min(posted_dates) if posted_dates else 0
            # Scope to this batch's source(s): without the old date gate a batch can
            # span weeks (EMITENNEWS), and the range would otherwise pull every
            # source's rows for that window.
            batch_sources = {s.sources for s in sitemaps if s.sources}

            query = session.query(SitemapTable.link, SitemapTable.posted_at, SitemapTable.sitemap_id).filter(
                SitemapTable.posted_at >= earliest_posted_at
            )
            if batch_sources:
                query = query.filter(SitemapTable.sources.in_(batch_sources))
            existing_rows = query.all()
            
            # Lookup Map: { (link, date) : id }
            existing_map = {
                (row.link, row.posted_at): row.sitemap_id 
                for row in existing_rows
            }

            new_entries_count = 0

            for sitemap in sitemaps:
                date_int = int(sitemap.posted_at.strftime("%Y%m%d")) if sitemap.posted_at else 0
                lookup_key = (sitemap.link, date_int)
                
                final_id = None

                # --- Scenario A: Check Cache/DB ---
                if lookup_key in existing_map:
                    final_id = existing_map[lookup_key]
                
                # --- Scenario B: Insert New ---
                else:
                    try:
                        with session.begin_nested():
                            entry = SitemapTable(sitemap)
                            session.add(entry)
                            session.flush() # Generate ID
                            
                            final_id = entry.sitemap_id
                            
                            # Update map for subsequent duplicates in this batch
                            existing_map[lookup_key] = final_id
                            new_entries_count += 1
                            
                    except Exception as e:
                        logger.error(f"Failed to save {sitemap.link}: {e}")
                        # If save fails, we can't get an ID. 
                        # We append the original object (with sitemap_id=None) and continue.
                        updated_sitemaps_list.append(sitemap)
                        continue

                # --- THE FIX: Create a new copy with the ID ---
                if final_id is not None:
                    # 'replace' creates a new instance of the frozen class
                    new_sitemap_obj = replace(sitemap, sitemap_id=final_id)
                    updated_sitemaps_list.append(new_sitemap_obj)
                else:
                    updated_sitemaps_list.append(sitemap)
            
            try:
                session.commit()
                logger.info(f"Batch complete. Saved {new_entries_count} new sitemaps.")
            except Exception as e:
                logger.error(f"Critical commit error: {e}")
                session.rollback()
                # If commit fails, the IDs generated in this transaction are technically invalid in DB,
                # but we return what we attempted.
            
            return updated_sitemaps_list

    def load_all_sitemaps(
        self, website: str, n_limit: int
    ) -> List[NewsSitemapModel]:
        website = f"'{website}'"
        news_list = []
        with self.client.get_session() as session:
            query = (
                f"SELECT a.{SitemapTable.link.name}, a.{SitemapTable.sitemap_id.name}, "
                f"a.{SitemapTable.headline.name}, a.{SitemapTable.posted_at.name}, "
                f"a.{SitemapTable.sources.name}, a.{SitemapTable.category.name}, a.{SitemapTable.keywords.name} "
                f"FROM {SitemapTable.__tablename__} as a "
                f"LEFT JOIN (SELECT {NewsArticlesTable.sitemap_id.name} "
                f"FROM {NewsArticlesTable.__tablename__}) as b "
                f"ON a.{SitemapTable.sitemap_id.name} = b.{NewsArticlesTable.sitemap_id.name} "
                f"WHERE {SitemapTable.sources.name} = {website} "
                f"AND b.{NewsArticlesTable.sitemap_id.name} is NULL "
                f"AND (a.{SitemapTable.last_crawl_attempt.name} IS NULL "
                f"     OR a.{SitemapTable.last_crawl_attempt.name} < NOW() - INTERVAL '{SITEMAP_RECRAWL_COOLDOWN_DAYS} days') "
                f"ORDER BY a.{SitemapTable.posted_at.name} DESC "
                f"LIMIT {n_limit}"
            )

            result = session.execute(text(query))
            for row in result:
                # Convert posted_at from int (yyyyMMdd) to datetime
                posted_at_dt = None
                if row[3]:
                    posted_at_dt = datetime.strptime(str(row[3]), "%Y%m%d")
                news = NewsSitemapModel(
                    link=row[0],
                    sitemap_id=row[1],
                    headline=row[2],
                    posted_at=posted_at_dt,  # Use the converted datetime
                    sources=row[4],
                    category=row[5],
                    keywords=row[6],
                )
                news_list.append(news)
        return news_list

    def mark_sitemaps_attempted(self, sitemap_ids):
        """Stamp last_crawl_attempt=NOW() for the given sitemap_ids so they are not
        re-crawled until the cooldown window elapses (Bug B fix)."""
        if not sitemap_ids:
            return
        with self.client.get_session() as session:
            session.execute(
                text(
                    f"UPDATE {SitemapTable.__tablename__} "
                    f"SET {SitemapTable.last_crawl_attempt.name} = NOW() "
                    f"WHERE {SitemapTable.sitemap_id.name} = ANY(:ids)"
                ),
                {"ids": list(sitemap_ids)},
            )
            session.commit()