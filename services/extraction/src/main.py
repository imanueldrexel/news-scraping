"""
Extraction Engine - Main Entry Point

This service consumes preprocessed content, extracts knowledge
graph triplets using Ollama LLM, and publishes for entity resolution.
"""

import logging
import sys
import time
from datetime import datetime, timezone
from typing import List

from src.config import get_settings
from src.triplet_extractor import TripletExtractor, ExtractedTriplet

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.redis_client.stream_producer import RedisStreamProducer
from shared.schemas.preprocessed_message import PreprocessedContentMessage
from shared.schemas.triplet_message import (
    TripletExtractionMessage,
    Triplet,
    EntityType,
    RelationType,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ExtractionService:
    """
    Main extraction service that:
    1. Consumes preprocessed content
    2. Extracts triplets using Ollama LLM
    3. Publishes triplets for entity resolution
    """

    def __init__(self):
        self.settings = get_settings()

        # Initialize triplet extractor
        self.extractor = TripletExtractor(
            base_url=self.settings.ollama_url,
            model=self.settings.llm_model,
            timeout=self.settings.llm_timeout,
            min_confidence=self.settings.min_confidence,
        )

        # Initialize Redis clients
        self.consumer = RedisStreamConsumer(
            redis_url=self.settings.redis_url,
            group=self.settings.consumer_group,
            consumer=self.settings.consumer_name,
            batch_size=self.settings.batch_size,
        )
        self.producer = RedisStreamProducer(
            redis_url=self.settings.redis_url,
        )

        # Stats
        self.stats = {
            "processed": 0,
            "triplets_extracted": 0,
            "empty_extractions": 0,
            "errors": 0,
        }

        logger.info("Initialized ExtractionService")

    def wait_for_ollama(self, max_retries: int = 30, delay: int = 10) -> bool:
        """Wait for Ollama to be available."""
        logger.info("Waiting for Ollama...")

        for i in range(max_retries):
            if self.extractor.is_available():
                logger.info(f"Ollama ready with model {self.settings.llm_model}")
                return True

            logger.info(f"Waiting for Ollama (attempt {i+1}/{max_retries})")
            time.sleep(delay)

        logger.error("Ollama not available after max retries")
        return False

    def _convert_triplets(
        self, extracted: List[ExtractedTriplet]
    ) -> List[Triplet]:
        """Convert extracted triplets to schema format."""
        result = []

        for t in extracted:
            try:
                # Convert entity types
                try:
                    subject_type = EntityType(t.subject_type)
                except ValueError:
                    subject_type = EntityType.PERSON

                try:
                    object_type = EntityType(t.object_type)
                except ValueError:
                    object_type = EntityType.PERSON

                # Convert relation type
                try:
                    predicate = RelationType(t.predicate)
                except ValueError:
                    predicate = RelationType.RELATED_TO

                result.append(
                    Triplet(
                        subject=t.subject,
                        subject_type=subject_type,
                        predicate=predicate,
                        object=t.object,
                        object_type=object_type,
                        confidence=t.confidence,
                        source_chunk_id=t.source_chunk_id,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to convert triplet: {e}")

        return result

    def process_message(self, message: StreamMessage) -> bool:
        """
        Process a single message from the preprocessed stream.

        Args:
            message: StreamMessage from Redis

        Returns:
            True if processed successfully
        """
        try:
            # Parse preprocessed content
            preprocessed = PreprocessedContentMessage.from_redis_dict(message.data)
            logger.debug(f"Extracting from: {preprocessed.url[:50]}...")

            # Prepare chunks for extraction
            chunks = preprocessed.chunks[: self.settings.max_chunks_per_article]
            chunk_data = [
                {"text": c.text, "chunk_id": c.chunk_id}
                for c in chunks
            ]

            # Extract triplets
            extracted = self.extractor.extract_from_chunks(chunk_data)

            if not extracted:
                logger.debug(f"No triplets extracted from {preprocessed.headline[:30]}")
                self.stats["empty_extractions"] += 1
                return True  # Acknowledge but no output

            # Convert to schema format
            triplets = self._convert_triplets(extracted)
            self.stats["triplets_extracted"] += len(triplets)

            # Create extraction message
            extraction_msg = TripletExtractionMessage(
                original_message_id=preprocessed.message_id,
                url=preprocessed.url,
                source=preprocessed.source,
                headline=preprocessed.headline,
                category=preprocessed.category,
                sitemap_id=preprocessed.sitemap_id,
                published_at=preprocessed.published_at,
                triplets=triplets,
                extraction_model=self.settings.llm_model,
                chunks_processed=len(chunks),
                extracted_at=datetime.now(timezone.utc),
            )

            # Publish to output stream
            self.producer.publish(
                stream=self.settings.output_stream,
                message=extraction_msg.to_redis_dict(),
            )

            self.stats["processed"] += 1
            logger.info(
                f"Extracted {len(triplets)} triplets from: {preprocessed.headline[:40]}..."
            )

            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False

    def run(self):
        """Run the extraction service continuously."""
        logger.info("Starting Extraction Engine")
        logger.info(f"Input stream: {self.settings.input_stream}")
        logger.info(f"Output stream: {self.settings.output_stream}")
        logger.info(f"LLM model: {self.settings.llm_model}")

        # Wait for Ollama
        if not self.wait_for_ollama():
            logger.error("Failed to start: Ollama not available")
            return

        try:
            self.consumer.consume(
                streams=[self.settings.input_stream],
                handler=self.process_message,
            )
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.print_stats()
            self.close()

    def print_stats(self):
        """Print processing statistics."""
        logger.info("=" * 50)
        logger.info("Extraction Engine Statistics:")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Triplets extracted: {self.stats['triplets_extracted']}")
        logger.info(f"  Empty extractions: {self.stats['empty_extractions']}")
        logger.info(f"  Errors: {self.stats['errors']}")

        if self.stats["processed"] > 0:
            avg = self.stats["triplets_extracted"] / self.stats["processed"]
            logger.info(f"  Avg triplets per article: {avg:.1f}")

    def close(self):
        """Clean up resources."""
        self.consumer.close()
        self.producer.close()
        self.extractor.close()


def main():
    """Main entry point."""
    service = ExtractionService()
    service.run()


if __name__ == "__main__":
    main()
