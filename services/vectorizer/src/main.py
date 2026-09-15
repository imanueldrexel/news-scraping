"""
Vectorizer Service - Main Entry Point

This service consumes preprocessed content, generates embeddings
using Ollama, stores them in ChromaDB, and publishes for downstream.
"""

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional
import hashlib

from src.config import get_settings
from src.embedding_service import OllamaEmbeddingService
from src.chromadb_client import ChromaDBClient

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.redis_client.stream_producer import RedisStreamProducer
from shared.schemas.preprocessed_message import PreprocessedContentMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class VectorizerService:
    """
    Main vectorizer service that:
    1. Consumes preprocessed content
    2. Generates embeddings using Ollama
    3. Stores embeddings in ChromaDB
    4. Publishes to output stream for Analyst service
    """

    def __init__(self):
        self.settings = get_settings()

        # Initialize components
        self.embedding_service = OllamaEmbeddingService(
            base_url=self.settings.ollama_url,
            model=self.settings.embedding_model,
        )
        self.chromadb = ChromaDBClient(
            host=self.settings.chromadb_host,
            port=self.settings.chromadb_port,
            collection_name=self.settings.collection_name,
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
            "stored": 0,
            "duplicates": 0,
            "errors": 0,
        }

        logger.info("Initialized VectorizerService")

    def wait_for_services(self, max_retries: int = 30, delay: int = 10):
        """Wait for Ollama and ChromaDB to be available."""
        logger.info("Waiting for dependencies...")

        for i in range(max_retries):
            ollama_ready = self.embedding_service.is_available()
            chroma_ready = self.chromadb.is_available()

            if ollama_ready and chroma_ready:
                logger.info("All dependencies ready")
                return True

            status = []
            if not ollama_ready:
                status.append("Ollama")
            if not chroma_ready:
                status.append("ChromaDB")

            logger.info(
                f"Waiting for: {', '.join(status)} (attempt {i+1}/{max_retries})"
            )
            time.sleep(delay)

        logger.error("Dependencies not available after max retries")
        return False

    def _generate_doc_id(self, url: str) -> str:
        """Generate a document ID from URL."""
        return hashlib.md5(url.encode()).hexdigest()

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
            logger.debug(f"Processing: {preprocessed.url[:50]}...")

            # Generate document ID
            doc_id = self._generate_doc_id(preprocessed.url)

            # Check if already in ChromaDB
            if self.chromadb.document_exists(doc_id):
                logger.debug(f"Document already exists: {doc_id}")
                self.stats["duplicates"] += 1
                return True

            # Generate embedding for title + summary
            embed_text = f"{preprocessed.headline}\n\n{preprocessed.summary}"
            embedding = self.embedding_service.embed(embed_text)

            # Prepare metadata
            metadata = {
                "url": preprocessed.url,
                "headline": preprocessed.headline,
                "source": preprocessed.source,
                "category": preprocessed.category or "",
                "published_at": preprocessed.published_at.isoformat()
                if preprocessed.published_at
                else "",
                "sitemap_id": preprocessed.sitemap_id or 0,
                "relevance_score": preprocessed.relevance_score,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            # Store in ChromaDB
            self.chromadb.add_document(
                doc_id=doc_id,
                embedding=embedding,
                text=preprocessed.summary,
                metadata=metadata,
            )
            self.stats["stored"] += 1

            # Publish to output stream with embedding info
            output_data = {
                "message_id": preprocessed.message_id,
                "original_message_id": preprocessed.original_message_id,
                "url": preprocessed.url,
                "source": preprocessed.source,
                "headline": preprocessed.headline,
                "category": preprocessed.category or "",
                "published_at": preprocessed.published_at.isoformat()
                if preprocessed.published_at
                else "",
                "doc_id": doc_id,
                "embedding_model": self.settings.embedding_model,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            self.producer.publish(
                stream=self.settings.output_stream,
                message=output_data,
            )

            self.stats["processed"] += 1
            logger.info(f"Vectorized: {preprocessed.headline[:50]}...")

            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False

    def run(self):
        """Run the vectorizer service continuously."""
        logger.info("Starting Vectorizer Service")
        logger.info(f"Input stream: {self.settings.input_stream}")
        logger.info(f"Output stream: {self.settings.output_stream}")
        logger.info(f"Embedding model: {self.settings.embedding_model}")

        # Wait for dependencies
        if not self.wait_for_services():
            logger.error("Failed to start: dependencies not available")
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
        logger.info("Vectorizer Statistics:")
        logger.info(f"  Processed: {self.stats['processed']}")
        logger.info(f"  Stored: {self.stats['stored']}")
        logger.info(f"  Duplicates: {self.stats['duplicates']}")
        logger.info(f"  Errors: {self.stats['errors']}")

        # ChromaDB stats
        try:
            chroma_stats = self.chromadb.get_collection_stats()
            logger.info(f"  ChromaDB documents: {chroma_stats.get('document_count', 0)}")
        except Exception:
            pass

    def close(self):
        """Clean up resources."""
        self.consumer.close()
        self.producer.close()
        self.embedding_service.close()


def main():
    """Main entry point."""
    service = VectorizerService()
    service.run()


if __name__ == "__main__":
    main()
