"""Entity Resolver Service - Main Entry Point."""

import logging
import sys
from datetime import datetime, timezone

from src.config import get_settings
from src.normalizer import IndonesianNameNormalizer
from src.deduplicator import EntityDeduplicator

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.redis_client.stream_producer import RedisStreamProducer
from shared.schemas.triplet_message import TripletExtractionMessage
from shared.schemas.entity_message import (
    ResolvedEntitiesMessage,
    ResolvedEntity,
    ResolvedRelation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class EntityResolverService:
    """Resolves and normalizes entities from extracted triplets."""

    def __init__(self):
        self.settings = get_settings()
        self.normalizer = IndonesianNameNormalizer()
        self.deduplicator = EntityDeduplicator(
            redis_url=self.settings.redis_url,
            threshold=self.settings.fuzzy_threshold,
        )
        self.consumer = RedisStreamConsumer(
            redis_url=self.settings.redis_url,
            group=self.settings.consumer_group,
            consumer=self.settings.consumer_name,
            batch_size=self.settings.batch_size,
        )
        self.producer = RedisStreamProducer(redis_url=self.settings.redis_url)
        self.stats = {"processed": 0, "entities_resolved": 0, "relations": 0, "errors": 0}

    def process_message(self, message: StreamMessage) -> bool:
        try:
            triplet_msg = TripletExtractionMessage.from_redis_dict(message.data)

            if not triplet_msg.triplets:
                return True

            entities = {}
            relations = []

            for triplet in triplet_msg.triplets:
                # Normalize and deduplicate subject
                subj_canonical, subj_original = self.normalizer.normalize(
                    triplet.subject, triplet.subject_type.value
                )
                subj_canonical = self.deduplicator.get_or_create(
                    subj_canonical, triplet.subject_type.value
                )

                # Normalize and deduplicate object
                obj_canonical, obj_original = self.normalizer.normalize(
                    triplet.object, triplet.object_type.value
                )
                obj_canonical = self.deduplicator.get_or_create(
                    obj_canonical, triplet.object_type.value
                )

                # Track unique entities
                subj_key = f"{triplet.subject_type.value}:{subj_canonical}"
                if subj_key not in entities:
                    entities[subj_key] = ResolvedEntity(
                        canonical_name=subj_canonical,
                        original_name=subj_original,
                        entity_type=triplet.subject_type.value,
                        aliases=self.normalizer.get_aliases(subj_canonical),
                    )

                obj_key = f"{triplet.object_type.value}:{obj_canonical}"
                if obj_key not in entities:
                    entities[obj_key] = ResolvedEntity(
                        canonical_name=obj_canonical,
                        original_name=obj_original,
                        entity_type=triplet.object_type.value,
                        aliases=self.normalizer.get_aliases(obj_canonical),
                    )

                # Create resolved relation
                relations.append(
                    ResolvedRelation(
                        subject=entities[subj_key],
                        predicate=triplet.predicate.value,
                        object=entities[obj_key],
                        confidence=triplet.confidence,
                        article_url=triplet_msg.url,
                        article_headline=triplet_msg.headline,
                    )
                )

            # Create output message
            resolved_msg = ResolvedEntitiesMessage(
                original_message_id=triplet_msg.message_id,
                url=triplet_msg.url,
                source=triplet_msg.source,
                headline=triplet_msg.headline,
                sitemap_id=triplet_msg.sitemap_id,
                published_at=triplet_msg.published_at,
                entities=list(entities.values()),
                relations=relations,
                resolved_at=datetime.now(timezone.utc),
            )

            self.producer.publish(
                stream=self.settings.output_stream,
                message=resolved_msg.to_redis_dict(),
            )

            self.stats["processed"] += 1
            self.stats["entities_resolved"] += len(entities)
            self.stats["relations"] += len(relations)

            logger.info(
                f"Resolved {len(entities)} entities, {len(relations)} relations "
                f"from: {triplet_msg.headline[:40]}..."
            )
            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False

    def run(self):
        logger.info("Starting Entity Resolver Service")
        try:
            self.consumer.consume(
                streams=[self.settings.input_stream],
                handler=self.process_message,
            )
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            logger.info(f"Stats: {self.stats}")
            self.consumer.close()
            self.producer.close()
            self.deduplicator.close()


def main():
    EntityResolverService().run()


if __name__ == "__main__":
    main()
