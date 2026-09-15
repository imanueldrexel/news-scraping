"""Redis-based URL deduplication to prevent re-scraping."""

import redis
import hashlib
import logging
from typing import Set

logger = logging.getLogger(__name__)


class RedisDeduplicator:
    """
    Redis-based deduplication for URLs.
    Uses Redis SET with TTL to track recently processed URLs.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        ttl_days: int = 7,
        key_prefix: str = "dedup:url:",
    ):
        """
        Initialize deduplicator.

        Args:
            redis_url: Redis connection URL
            ttl_days: Days to keep URL in dedup cache
            key_prefix: Redis key prefix
        """
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl_days * 86400  # Convert to seconds
        self.key_prefix = key_prefix
        self.set_key = "dedup:urls:set"

    def _hash_url(self, url: str) -> str:
        """Create a hash of the URL for storage."""
        return hashlib.md5(url.encode()).hexdigest()

    def is_duplicate(self, url: str) -> bool:
        """
        Check if URL was already processed.

        Args:
            url: URL to check

        Returns:
            True if URL is a duplicate
        """
        url_hash = self._hash_url(url)
        key = f"{self.key_prefix}{url_hash}"
        return self.redis.exists(key) == 1

    def mark_processed(self, url: str) -> None:
        """
        Mark URL as processed with TTL.

        Args:
            url: URL to mark as processed
        """
        url_hash = self._hash_url(url)
        key = f"{self.key_prefix}{url_hash}"
        self.redis.setex(key, self.ttl, url)
        logger.debug(f"Marked URL as processed: {url[:50]}...")

    def mark_batch_processed(self, urls: list[str]) -> None:
        """
        Mark multiple URLs as processed using pipeline.

        Args:
            urls: List of URLs to mark
        """
        if not urls:
            return

        pipe = self.redis.pipeline()
        for url in urls:
            url_hash = self._hash_url(url)
            key = f"{self.key_prefix}{url_hash}"
            pipe.setex(key, self.ttl, url)
        pipe.execute()
        logger.debug(f"Marked {len(urls)} URLs as processed")

    def filter_new_urls(self, urls: list[str]) -> list[str]:
        """
        Filter out already processed URLs.

        Args:
            urls: List of URLs to filter

        Returns:
            List of new (not processed) URLs
        """
        if not urls:
            return []

        pipe = self.redis.pipeline()
        for url in urls:
            url_hash = self._hash_url(url)
            key = f"{self.key_prefix}{url_hash}"
            pipe.exists(key)

        results = pipe.execute()

        new_urls = [url for url, exists in zip(urls, results) if not exists]
        logger.info(f"Filtered {len(urls)} URLs -> {len(new_urls)} new URLs")
        return new_urls

    def get_stats(self) -> dict:
        """Get deduplication statistics."""
        # Count keys with prefix (approximate)
        cursor = 0
        count = 0
        pattern = f"{self.key_prefix}*"

        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=1000)
            count += len(keys)
            if cursor == 0:
                break

        return {
            "tracked_urls": count,
            "ttl_days": self.ttl // 86400,
        }

    def clear(self) -> int:
        """
        Clear all dedup keys (use with caution).

        Returns:
            Number of keys deleted
        """
        pattern = f"{self.key_prefix}*"
        cursor = 0
        total_deleted = 0

        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=1000)
            if keys:
                total_deleted += self.redis.delete(*keys)
            if cursor == 0:
                break

        logger.warning(f"Cleared {total_deleted} dedup keys")
        return total_deleted

    def close(self):
        """Close Redis connection."""
        self.redis.close()
