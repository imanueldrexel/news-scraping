"""Fuzzy entity deduplication."""

import redis
import logging
from typing import Optional, Dict, List
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class EntityDeduplicator:
    """
    Fuzzy matching deduplicator for entities.
    Uses Redis to cache known entities.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        threshold: float = 0.85,
    ):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.threshold = threshold
        self.key_prefix = "entity:"

    def _make_key(self, entity_type: str, name: str) -> str:
        """Create Redis key for entity."""
        return f"{self.key_prefix}{entity_type}:{name.lower()}"

    def find_match(self, name: str, entity_type: str) -> Optional[str]:
        """
        Find existing entity matching the given name.

        Args:
            name: Entity name to match
            entity_type: Type of entity

        Returns:
            Canonical name if match found, None otherwise
        """
        # First try exact match
        key = self._make_key(entity_type, name)
        exact = self.redis.get(key)
        if exact:
            return exact

        # Fuzzy match against cached entities of same type
        pattern = f"{self.key_prefix}{entity_type}:*"
        best_match = None
        best_score = 0

        for cached_key in self.redis.scan_iter(match=pattern, count=100):
            cached_name = self.redis.get(cached_key)
            if not cached_name:
                continue

            # Calculate similarity
            score = fuzz.ratio(name.lower(), cached_name.lower()) / 100

            if score >= self.threshold and score > best_score:
                best_score = score
                best_match = cached_name

        return best_match

    def register_entity(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """
        Register entity in cache.

        Args:
            canonical_name: Canonical entity name
            entity_type: Type of entity
            aliases: Optional list of aliases
        """
        # Register canonical name
        key = self._make_key(entity_type, canonical_name)
        self.redis.set(key, canonical_name)

        # Register aliases
        if aliases:
            for alias in aliases:
                alias_key = self._make_key(entity_type, alias)
                self.redis.set(alias_key, canonical_name)

    def get_or_create(
        self,
        name: str,
        entity_type: str,
        aliases: Optional[List[str]] = None,
    ) -> str:
        """
        Get existing match or create new entity.

        Args:
            name: Entity name
            entity_type: Type of entity
            aliases: Optional aliases

        Returns:
            Canonical name (existing or new)
        """
        # Try to find existing match
        existing = self.find_match(name, entity_type)
        if existing:
            return existing

        # Register new entity
        self.register_entity(name, entity_type, aliases)
        return name

    def get_stats(self) -> Dict:
        """Get entity cache statistics."""
        counts = {}
        for entity_type in ["PERSON", "COMPANY", "ORGANIZATION", "GOVERNMENT", "LOCATION"]:
            pattern = f"{self.key_prefix}{entity_type}:*"
            count = sum(1 for _ in self.redis.scan_iter(match=pattern))
            counts[entity_type] = count

        return {"entities_by_type": counts, "total": sum(counts.values())}

    def close(self):
        """Close Redis connection."""
        self.redis.close()
