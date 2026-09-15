"""
Preprocessor Service - Main Entry Point

This service consumes raw HTML from Redis Streams,
cleans it, checks relevance, chunks it, and publishes
preprocessed content for downstream services.
"""

import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from src.config import get_settings
from src.html_cleaner import HTMLCleaner
from src.relevance_checker import RelevanceChecker
from src.chunker import TextChunker

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.redis_client.stream_producer import RedisStreamProducer
from shared.schemas.ingestion_message import IngestedContentMessage
from shared.schemas.preprocessed_message import PreprocessedContentMessage, TextChunk

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class PreprocessorService:
    """
    Main preprocessor service that:
    1. Consumes raw HTML from ingestion stream
    2. Cleans HTML to extract text
    3. Checks relevance to financial/economic topics
    4. Chunks text for LLM processing
    5. Publishes preprocessed content
    """

    def __init__(self):
        self.settings = get_settings()

        # Initialize components
        self.cleaner = HTMLCleaner()
        self.relevance_checker = RelevanceChecker(
            keywords=self.settings.interests,
            threshold=self.settings.relevance_threshold,
            use_semantic=self.settings.use_semantic_filter,
        )
        self.chunker = TextChunker(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
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
            "relevant": 0,
            "irrelevant": 0,
            "errors": 0,
        }

        logger.info("Initialized PreprocessorService")

    def process_message(self, message: StreamMessage) -> bool:
        """
        Process a single message from the ingestion stream.

        Args:
            message: StreamMessage from Redis

        Returns:
            True if processed successfully
        """
        try:
            # Parse ingested content
            ingested = IngestedContentMessage.from_redis_dict(message.data)
            logger.debug(f"Processing: {ingested.url[:50]}...")

            # Clean HTML
            clean_text, reporter = self.cleaner.clean(
                ingested.html, ingested.source
            )

            if not clean_text or len(clean_text) < 100:
                logger.warning(f"Insufficient text extracted from {ingested.url}")
                self.stats["errors"] += 1
                return True  # Acknowledge to avoid retry

            # Check relevance
            is_relevant, relevance_score = self.relevance_checker.check_relevance(
                clean_text
            )

            if not is_relevant:
                logger.debug(
                    f"Article not relevant (score={relevance_score:.2f}): {ingested.headline[:50]}"
                )
                self.stats["irrelevant"] += 1
                return True  # Acknowledge but don't forward

            # Get summary (first few sentences)
            summary = self.cleaner.get_summary(clean_text, max_sentences=3)

            # Chunk text
            chunks = self.chunker.chunk(clean_text)
            chunk_dicts = [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "token_count": c.token_count,
                    "start_char": c.start_char,
                    "end_char": c.end_char,
                }
                for c in chunks
            ]

            # Create preprocessed message
            preprocessed = PreprocessedContentMessage(
                original_message_id=ingested.message_id,
                url=ingested.url,
                source=ingested.source,
                headline=ingested.headline,
                category=ingested.category,
                published_at=ingested.published_at,
                sitemap_id=ingested.sitemap_id,
                clean_text=clean_text,
                summary=summary,
                reporter=reporter,
                chunks=[TextChunk(**c) for c in chunk_dicts],
                relevance_score=relevance_score,
                is_relevant=is_relevant,
                processed_at=datetime.now(timezone.utc),
            )

            # Publish to output stream
            self.producer.publish(
                stream=self.settings.output_stream,
                message=preprocessed.to_redis_dict(),
            )

            self.stats["processed"] += 1
            self.stats["relevant"] += 1
            logger.info(
                f"Preprocessed: {ingested.headline[:50]}... "
                f"(score={relevance_score:.2f}, chunks={len(chunks)})"
            )

            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False  # Will be retried

    def run(self):
        """Run the preprocessor service continuously."""
        logger.info("Starting Preprocessor Service")
        logger.info(f"Input stream: {self.settings.input_stream}")
        logger.info(f"Output stream: {self.settings.output_stream}")
        logger.info(f"Relevance threshold: {self.settings.relevance_threshold}")

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
        logger.info("Preprocessor Statistics:")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Relevant: {self.stats['relevant']}")
        logger.info(f"  Irrelevant: {self.stats['irrelevant']}")
        logger.info(f"  Errors: {self.stats['errors']}")

    def close(self):
        """Clean up resources."""
        self.consumer.close()
        self.producer.close()


def main():
    """Main entry point."""
    service = PreprocessorService()
    service.run()


if __name__ == "__main__":
    main()
