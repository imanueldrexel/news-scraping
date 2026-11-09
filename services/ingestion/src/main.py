"""
Ingestion Service - Main Entry Point

This service monitors news site sitemaps for new articles,
fetches their HTML content, and publishes to Redis Streams.
Includes failure detection for news outlets that fail to scrape.
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict

from src.config import get_settings
from src.content_fetcher import ContentFetcher
from src.deduplication import RedisDeduplicator
from src.sitemap_monitor import (
    SitemapMonitor,
    ArticleMetadata,
    CRAWLER_CONFIGS,
    CrawlerConfig,
    ScrapeResult,
    ScrapeStatus,
)

from shared.redis_client.stream_producer import RedisStreamProducer
from shared.schemas.ingestion_message import IngestedContentMessage
from shared.schemas.stream_names import StreamNames
from shared.telegram import TelegramNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class IngestionService:
    """
    Main ingestion service that orchestrates:
    1. Sitemap monitoring with failure detection
    2. Content fetching
    3. Deduplication
    4. Publishing to Redis Streams
    """

    def __init__(self):
        self.settings = get_settings()

        # Initialize components
        self.fetcher = ContentFetcher(
            max_workers=self.settings.max_workers,
        )
        self.monitor = SitemapMonitor(self.fetcher)
        self.deduplicator = RedisDeduplicator(
            redis_url=self.settings.redis_url,
            ttl_days=self.settings.dedup_ttl_days,
        )
        self.producer = RedisStreamProducer(
            redis_url=self.settings.redis_url,
        )
        self.telegram = TelegramNotifier(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
        )

        # Track sources to crawl
        self.active_sources: List[str] = list(CRAWLER_CONFIGS.keys())

        # Track scrape results per cycle
        self._cycle_results: Dict[str, ScrapeResult] = {}

        logger.info(f"Initialized IngestionService with {len(self.active_sources)} sources")

    def set_sources(self, sources: List[str]):
        """
        Set which sources to crawl.

        Args:
            sources: List of source names (e.g., ["BISNIS", "KONTAN"])
        """
        valid_sources = [s for s in sources if s in CRAWLER_CONFIGS]
        self.active_sources = valid_sources
        logger.info(f"Active sources set to: {valid_sources}")

    def discover_articles(self, source_name: str) -> tuple[List[ArticleMetadata], ScrapeResult]:
        """
        Discover new articles from a source's sitemap.

        Args:
            source_name: Name of the news source

        Returns:
            Tuple of (List of new article metadata, ScrapeResult)
        """
        config = CRAWLER_CONFIGS.get(source_name)
        if not config:
            logger.warning(f"Unknown source: {source_name}")
            return [], ScrapeResult(
                source_name=source_name,
                status=ScrapeStatus.FAILED,
                total_articles=0,
                branches_scraped=0,
                branches_failed=0,
                error="Unknown source configuration",
            )

        # Get all articles from sitemap with detailed result
        all_articles, scrape_result = self.monitor.scrape_all_branches(config)

        # Store result for this cycle
        self._cycle_results[source_name] = scrape_result

        if not all_articles:
            return [], scrape_result

        # Filter by article age (timestamp-based deduplication)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.settings.max_article_age_hours)
        recent_articles = []
        skipped_old = 0
        for a in all_articles:
            if a.published_at is None:
                # No timestamp - include it (will be caught by URL dedup)
                recent_articles.append(a)
            elif a.published_at >= cutoff_time:
                recent_articles.append(a)
            else:
                skipped_old += 1
        
        if skipped_old > 0:
            logger.info(f"Skipped {skipped_old} articles older than {self.settings.max_article_age_hours}h for {source_name}")
        
        if not recent_articles:
            logger.info(f"No recent articles from {source_name} (all older than {self.settings.max_article_age_hours}h)")
            return [], scrape_result

        # Filter out duplicates (URL-based)
        urls = [a.url for a in recent_articles]
        new_urls = self.deduplicator.filter_new_urls(urls)

        # Return only new articles
        new_articles = [a for a in recent_articles if a.url in new_urls]

        # Limit per cycle
        if len(new_articles) > self.settings.max_articles_per_source:
            new_articles = new_articles[: self.settings.max_articles_per_source]
            logger.info(
                f"Limited to {self.settings.max_articles_per_source} articles for {source_name}"
            )

        return new_articles, scrape_result

    def fetch_and_publish(self, articles: List[ArticleMetadata]) -> int:
        """
        Fetch article HTML and publish to Redis Streams.

        Args:
            articles: List of articles to fetch

        Returns:
            Number of successfully published articles
        """
        if not articles:
            return 0

        published_count = 0
        urls = [a.url for a in articles]

        # Fetch HTML in parallel
        logger.info(f"Fetching {len(urls)} articles...")
        fetch_results = self.fetcher.fetch_batch(urls)

        # Create URL -> result mapping
        result_map = {r.url: r for r in fetch_results}

        # Publish successful fetches
        for article in articles:
            result = result_map.get(article.url)
            if not result or not result.success:
                continue

            try:
                message = IngestedContentMessage(
                    url=article.url,
                    html=result.html,
                    source=article.source,
                    headline=article.headline,
                    category=article.category,
                    keywords=article.keywords,
                    published_at=article.published_at,
                    scraped_at=datetime.now(timezone.utc),
                )

                # Publish to Redis Stream
                self.producer.publish(
                    stream=self.settings.output_stream,
                    message=message.to_redis_dict(),
                )

                # Mark as processed
                self.deduplicator.mark_processed(article.url)
                published_count += 1

            except Exception as e:
                logger.error(f"Error publishing {article.url}: {e}")

        logger.info(f"Published {published_count}/{len(articles)} articles")
        return published_count

    def process_source(self, source_name: str) -> tuple[int, ScrapeResult]:
        """
        Process a single news source.

        Args:
            source_name: Name of the news source

        Returns:
            Tuple of (Number of articles published, ScrapeResult)
        """
        logger.info(f"Processing source: {source_name}")

        try:
            # Discover new articles with result tracking
            articles, scrape_result = self.discover_articles(source_name)

            if scrape_result.is_failed():
                logger.warning(f"Source {source_name} failed: {scrape_result.get_summary()}")
                return 0, scrape_result

            if not articles:
                logger.info(f"No new articles from {source_name}")
                return 0, scrape_result

            logger.info(f"Found {len(articles)} new articles from {source_name}")

            # Fetch and publish
            count = self.fetch_and_publish(articles)
            return count, scrape_result

        except Exception as e:
            logger.error(f"Error processing {source_name}: {e}")
            error_result = ScrapeResult(
                source_name=source_name,
                status=ScrapeStatus.FAILED,
                total_articles=0,
                branches_scraped=0,
                branches_failed=0,
                error=str(e),
            )
            self._cycle_results[source_name] = error_result
            return 0, error_result

    def run_cycle(self) -> dict:
        """
        Run one polling cycle for all active sources.

        Returns:
            Statistics dictionary
        """
        logger.info("=" * 60)
        logger.info("Starting ingestion cycle")
        cycle_start = datetime.now(timezone.utc)

        # Clear previous cycle results
        self._cycle_results.clear()

        stats = {
            "sources_processed": 0,
            "sources_successful": 0,
            "sources_failed": 0,
            "sources_empty": 0,
            "total_articles": 0,
            "errors": 0,
        }

        for source_name in self.active_sources:
            try:
                count, result = self.process_source(source_name)
                stats["total_articles"] += count
                stats["sources_processed"] += 1

                # Track success/failure
                if result.status == ScrapeStatus.FAILED:
                    stats["sources_failed"] += 1
                elif result.status == ScrapeStatus.EMPTY:
                    stats["sources_empty"] += 1
                else:
                    stats["sources_successful"] += 1

            except Exception as e:
                logger.error(f"Error with source {source_name}: {e}")
                stats["errors"] += 1
                stats["sources_failed"] += 1

        duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()

        # Log cycle summary
        logger.info("=" * 60)
        logger.info("CYCLE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration:.1f}s")
        logger.info(f"Sources processed: {stats['sources_processed']}")
        logger.info(f"Sources successful: {stats['sources_successful']}")
        logger.info(f"Sources failed: {stats['sources_failed']}")
        logger.info(f"Sources empty: {stats['sources_empty']}")
        logger.info(f"Total articles published: {stats['total_articles']}")

        # Log failure report if any failures
        failed_sources = self.monitor.get_failed_sources()
        if failed_sources:
            logger.warning("\n" + self.monitor.get_failure_report())

        # Log per-source summary
        self._log_source_summary()

        # Send Telegram notification
        asyncio.create_task(self._send_telegram_summary(stats, duration))

        return stats

    def _log_source_summary(self):
        """Log a summary of all source results for this cycle."""
        if not self._cycle_results:
            return

        logger.info("")
        logger.info("PER-SOURCE RESULTS:")
        logger.info("-" * 60)

        # Sort by status: failed first, then empty, then successful
        status_order = {
            ScrapeStatus.FAILED: 0,
            ScrapeStatus.EMPTY: 1,
            ScrapeStatus.PARTIAL: 2,
            ScrapeStatus.SUCCESS: 3,
        }

        sorted_results = sorted(
            self._cycle_results.items(),
            key=lambda x: (status_order.get(x[1].status, 4), x[0])
        )

        for source_name, result in sorted_results:
            status_icon = {
                ScrapeStatus.SUCCESS: "[OK]",
                ScrapeStatus.PARTIAL: "[PARTIAL]",
                ScrapeStatus.EMPTY: "[EMPTY]",
                ScrapeStatus.FAILED: "[FAILED]",
            }.get(result.status, "[?]")

            logger.info(
                f"  {status_icon:10} {source_name:20} - "
                f"{result.total_articles:4} articles, "
                f"{result.branches_scraped} branches, "
                f"{result.duration_seconds:.1f}s"
            )

        logger.info("-" * 60)

    def get_failed_sources(self) -> Dict[str, ScrapeResult]:
        """Get all currently failed sources."""
        return self.monitor.get_failed_sources()

    def get_failure_report(self) -> str:
        """Get a formatted failure report."""
        return self.monitor.get_failure_report()

    async def _send_telegram_summary(self, stats: dict, duration: float):
        """Send cycle summary to Telegram."""
        if not self.telegram.enabled:
            return

        # Build extra info with failure details
        extra_info = None
        failed_sources = self.get_failed_sources()
        if failed_sources:
            failed_names = ", ".join(failed_sources.keys())
            extra_info = f"⚠️ Failed sources: {failed_names}"

        try:
            await self.telegram.send_cycle_summary(
                service_name="Ingestion",
                stats=stats,
                duration_seconds=duration,
                extra_info=extra_info,
            )
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")

    async def run(self):
        """
        Run the ingestion service continuously.
        """
        logger.info("Starting Ingestion Service")
        logger.info(f"Polling interval: {self.settings.polling_interval}s")
        logger.info(f"Active sources: {len(self.active_sources)}")
        logger.info(f"Sources: {', '.join(self.active_sources)}")

        while True:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Error in run cycle: {e}")

            logger.info(
                f"Sleeping for {self.settings.polling_interval} seconds..."
            )
            await asyncio.sleep(self.settings.polling_interval)

    def close(self):
        """Clean up resources."""
        self.fetcher.close()
        self.deduplicator.close()
        self.producer.close()


async def main():
    """Main entry point."""
    service = IngestionService()

    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        # Print final failure report
        failed = service.get_failed_sources()
        if failed:
            logger.warning(f"\nFinal failure report ({len(failed)} sources):")
            logger.warning(service.get_failure_report())
        service.close()


if __name__ == "__main__":
    asyncio.run(main())
