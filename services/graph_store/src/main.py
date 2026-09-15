"""Graph Store Service - Main Entry Point."""

import logging
import sys
import time

from src.config import get_settings
from src.neo4j_client import Neo4jClient

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.schemas.entity_message import ResolvedEntitiesMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class GraphStoreService:
    """Stores resolved entities and relations in Neo4j."""

    def __init__(self):
        self.settings = get_settings()
        self.neo4j = Neo4jClient(
            uri=self.settings.neo4j_uri,
            user=self.settings.neo4j_user,
            password=self.settings.neo4j_password,
        )
        self.consumer = RedisStreamConsumer(
            redis_url=self.settings.redis_url,
            group=self.settings.consumer_group,
            consumer=self.settings.consumer_name,
            batch_size=self.settings.batch_size,
        )
        self.stats = {"processed": 0, "nodes_created": 0, "rels_created": 0, "errors": 0}

    def wait_for_neo4j(self, max_retries: int = 30, delay: int = 10) -> bool:
        logger.info("Waiting for Neo4j...")
        for i in range(max_retries):
            if self.neo4j.is_available():
                self.neo4j.init_schema()
                logger.info("Neo4j ready")
                return True
            logger.info(f"Waiting for Neo4j (attempt {i+1}/{max_retries})")
            time.sleep(delay)
        return False

    def process_message(self, message: StreamMessage) -> bool:
        try:
            resolved = ResolvedEntitiesMessage.from_redis_dict(message.data)

            # Create article node
            self.neo4j.upsert_article(
                url=resolved.url,
                headline=resolved.headline,
                source=resolved.source,
                published_at=resolved.published_at.isoformat() if resolved.published_at else None,
            )

            # Create entity nodes
            for entity in resolved.entities:
                self.neo4j.upsert_entity(
                    entity_type=entity.entity_type,
                    canonical_name=entity.canonical_name,
                    properties={"original_name": entity.original_name},
                    aliases=entity.aliases,
                )
                # Link to article
                self.neo4j.link_to_article(
                    entity_type=entity.entity_type,
                    entity_name=entity.canonical_name,
                    article_url=resolved.url,
                )
                self.stats["nodes_created"] += 1

            # Create relationships
            for relation in resolved.relations:
                self.neo4j.create_relationship(
                    from_type=relation.subject.entity_type,
                    from_name=relation.subject.canonical_name,
                    rel_type=relation.predicate,
                    to_type=relation.object.entity_type,
                    to_name=relation.object.canonical_name,
                    properties={"confidence": relation.confidence},
                )
                self.stats["rels_created"] += 1

            self.stats["processed"] += 1
            logger.info(
                f"Stored {len(resolved.entities)} nodes, {len(resolved.relations)} rels "
                f"from: {resolved.headline[:40]}..."
            )
            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False

    def run(self):
        logger.info("Starting Graph Store Service")

        if not self.wait_for_neo4j():
            logger.error("Neo4j not available")
            return

        try:
            self.consumer.consume(
                streams=[self.settings.input_stream],
                handler=self.process_message,
            )
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            logger.info(f"Stats: {self.stats}")
            logger.info(f"Graph stats: {self.neo4j.get_stats()}")
            self.consumer.close()
            self.neo4j.close()


def main():
    GraphStoreService().run()


if __name__ == "__main__":
    main()
