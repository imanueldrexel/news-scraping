from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from dataclasses import replace
import logging
from typing import Iterable, List, Dict, Tuple

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
    SitemapSaveResult,
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
from newscrawler.core.constants import SITEMAP_RECRAWL_COOLDOWN_DAYS, SITEMAP_MAX_FETCH_FAILURES

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemySitemapDataSource:
    # SYS-29: how many links go into one `link IN (...)` lookup. A source's whole
    # listing is saved in a single save_sitemaps call (VIVA lists 2,500+), so the
    # pre-fetch is chunked rather than rendered as one giant IN list.
    LINK_LOOKUP_CHUNK = 1000

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

    def find_existing_by_link(self, links: Iterable[str], session=None) -> Dict[str, int]:
        """SYS-29: map link -> sitemap_id for every link already stored.

        This is the exact lookup save_sitemaps dedups against -- exposed so
        scripts/experiments/probe_sitemap_dedup_drift.py can ask "which of these
        would save_sitemaps insert?" through the real code instead of re-deriving
        the key (the probe's original copy of the (link, posted_at) key is what let
        SYS-11's one-line change become a 3,817-row duplication event).

        The lookup is by link only, chunked (LINK_LOOKUP_CHUNK links per query).
        It is deliberately NOT scoped by posted_at or source: a stored row whose
        posted_at differs from today's derivation (SYS-11's +1-day WIB fix, a
        site re-stamping news:publication_date) still has to be found, and links
        already carry their domain so a source filter adds nothing.
        """
        links = sorted({l for l in links if l})
        if not links:
            return {}
        if session is None:
            with self.client.get_session() as s:
                return self.find_existing_by_link(links, session=s)
        existing: Dict[str, int] = {}
        for i in range(0, len(links), self.LINK_LOOKUP_CHUNK):
            rows = (
                session.query(SitemapTable.link, SitemapTable.sitemap_id)
                .filter(SitemapTable.link.in_(links[i:i + self.LINK_LOOKUP_CHUNK]))
                .all()
            )
            existing.update({row.link: row.sitemap_id for row in rows})
        return existing

    def save_sitemaps(self, sitemaps: List[NewsSitemapModel]) -> List[NewsSitemapModel]:
        if not sitemaps:
            return []

        # This will hold our new, updated objects
        updated_sitemaps_list = []

        with self.client.get_session() as session:
            # SYS-29: the dedup key is the link alone. A URL identifies an article;
            # the date was never part of its identity. Keying on (link, posted_at)
            # meant that any change in how posted_at is derived (SYS-11's WIB fix
            # moved every 00:00-06:59 article forward a day) or a site re-stamping
            # news:publication_date re-inserted a stored URL as a second sitemaps
            # row, which then had no articles row, re-entered load_all_sitemaps,
            # and produced a second articles row plus duplicate chunks and FAISS
            # vectors. scripts/migrate_sitemaps_unique_link.sql enforces the same
            # key in the database (sitemaps_link_uq), so this map is a fast path,
            # not the constraint -- a race between two writers now ends in the
            # per-row savepoint below, not in a duplicate row.
            #
            # An existing row's posted_at is deliberately left as first seen, even
            # when the re-listed entry carries a different date: the articles row
            # (meta_data.posted_at) was derived the same way at save time and would
            # otherwise disagree with its sitemap, and re-stamping sites would churn
            # the value on every crawl. Same rule as headline/keywords, which are
            # not refreshed on re-listing either.
            existing_map = self.find_existing_by_link((s.link for s in sitemaps), session=session)

            new_entries_count = 0

            for sitemap in sitemaps:
                lookup_key = sitemap.link

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
            
            # SYS-13: a failed commit must propagate. Swallowing it here returned
            # sitemap_ids generated by flush() inside a transaction that was just
            # rolled back -- the caller logged "Saved N sitemaps" and proceeded to
            # crawl articles for sitemap_ids that were never persisted. Let
            # get_session() roll back and re-raise so crawl_sitemaps -> log_crawl_failed
            # and the batch is marked failed instead of successful.
            session.commit()
            logger.info(f"Batch complete. Saved {new_entries_count} new sitemaps.")

            return SitemapSaveResult(updated_sitemaps_list, new_count=new_entries_count)

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
                # SYS-16: a sitemap the semantic filter already rejected is a
                # deterministic, permanent "no" (same headline/text, same
                # INTERESTS list) -- re-fetching it every cooldown window forever
                # wastes the per-run budget that should go to genuinely-pending
                # sitemaps. empty_extraction and pending both still retry normally,
                # since a layout fix or a first attempt can change their outcome.
                f"AND a.{SitemapTable.crawl_status.name} != 'rejected_filter' "
                f"AND (a.{SitemapTable.last_crawl_attempt.name} IS NULL "
                f"     OR a.{SitemapTable.last_crawl_attempt.name} < NOW() - INTERVAL '{SITEMAP_RECRAWL_COOLDOWN_DAYS} days') "
                # SYS-09: a URL that has failed to fetch/extract this many times in a
                # row is excluded permanently instead of consuming a retry slot on
                # every future run forever. A sitemap that has never been attempted,
                # or failed fewer times, is unaffected (fetch_failures defaults to 0).
                f"AND a.{SitemapTable.fetch_failures.name} < {SITEMAP_MAX_FETCH_FAILURES} "
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

    def increment_fetch_failures(self, sitemap_ids, error_msg: str = None):
        """SYS-09: bump fetch_failures for every sitemap_id that produced no
        NewsDetailsDTO this run (fetch failure or any exception in
        _get_news_details). Also stamps last_crawl_attempt=NOW() -- a permanently
        dead URL must still leave the cooldown queue like a successful attempt
        does, not just get counted. error_msg is necessarily coarse: the service
        layer only knows *which* sitemap_ids are missing from the batch's
        NewsDetailsDTO list, not each one's individual exception (that detail is
        logged, not returned, by _get_news_details)."""
        if not sitemap_ids:
            return
        with self.client.get_session() as session:
            session.execute(
                text(
                    f"UPDATE {SitemapTable.__tablename__} "
                    f"SET {SitemapTable.fetch_failures.name} = {SitemapTable.fetch_failures.name} + 1, "
                    f"    {SitemapTable.last_fetch_error.name} = :error_msg, "
                    f"    {SitemapTable.last_crawl_attempt.name} = NOW() "
                    f"WHERE {SitemapTable.sitemap_id.name} = ANY(:ids)"
                ),
                {"ids": list(sitemap_ids), "error_msg": error_msg},
            )
            session.commit()

    VALID_CRAWL_STATUSES = {"pending", "rejected_filter", "empty_extraction", "saved"}

    def mark_sitemaps_status(self, sitemap_ids, status: str):
        """SYS-16: set crawl_status for the given sitemap_ids, distinguishing a
        permanent semantic-filter rejection from a transient empty-extraction
        failure so load_all_sitemaps can exclude the former without changing the
        retry cooldown for the latter."""
        if not sitemap_ids:
            return
        if status not in self.VALID_CRAWL_STATUSES:
            raise ValueError(f"Invalid crawl_status: {status!r}")
        with self.client.get_session() as session:
            session.execute(
                text(
                    f"UPDATE {SitemapTable.__tablename__} "
                    f"SET {SitemapTable.crawl_status.name} = :status "
                    f"WHERE {SitemapTable.sitemap_id.name} = ANY(:ids)"
                ),
                {"status": status, "ids": list(sitemap_ids)},
            )
            session.commit()