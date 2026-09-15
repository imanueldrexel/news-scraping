"""Analyst Service - Main Entry Point."""

import logging
import sys
import time
import json
from datetime import datetime, timezone

from src.config import get_settings
from src.cluster_detector import ClusterDetector
from src.summarizer import MapReduceSummarizer

from shared.redis_client.stream_consumer import RedisStreamConsumer, StreamMessage
from shared.redis_client.stream_producer import RedisStreamProducer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AnalystService:
    """Detects article clusters and generates summaries."""

    def __init__(self):
        self.settings = get_settings()
        self.cluster_detector = ClusterDetector(
            host=self.settings.chromadb_host,
            port=self.settings.chromadb_port,
            similarity_threshold=self.settings.similarity_threshold,
        )
        self.summarizer = MapReduceSummarizer(
            base_url=self.settings.ollama_url,
            model=self.settings.llm_model,
        )
        self.consumer = RedisStreamConsumer(
            redis_url=self.settings.redis_url,
            group=self.settings.consumer_group,
            consumer=self.settings.consumer_name,
            batch_size=self.settings.batch_size,
        )
        self.producer = RedisStreamProducer(redis_url=self.settings.redis_url)
        self.stats = {"processed": 0, "clusters_found": 0, "summaries_generated": 0, "errors": 0}

        # Track recently summarized clusters to avoid duplicates
        self._summarized_clusters = set()

    def wait_for_dependencies(self, max_retries: int = 30, delay: int = 10) -> bool:
        logger.info("Waiting for dependencies...")
        for i in range(max_retries):
            ollama_ready = self.summarizer.is_available()
            if ollama_ready:
                logger.info("Dependencies ready")
                return True
            logger.info(f"Waiting (attempt {i+1}/{max_retries})")
            time.sleep(delay)
        return False

    def process_message(self, message: StreamMessage) -> bool:
        try:
            data = message.data
            doc_id = data.get("doc_id", "")
            headline = data.get("headline", "")
            url = data.get("url", "")

            if not doc_id:
                return True

            # Find similar articles
            similar = self.cluster_detector.find_similar(
                doc_id=doc_id,
                n_results=10,
            )

            if len(similar) < self.settings.min_cluster_size - 1:
                logger.debug(f"No significant cluster for: {headline[:40]}...")
                self.stats["processed"] += 1
                return True

            self.stats["clusters_found"] += 1

            # Create cluster key for dedup
            cluster_ids = sorted([doc_id] + [s["id"] for s in similar[:3]])
            cluster_key = ":".join(cluster_ids[:3])

            if cluster_key in self._summarized_clusters:
                logger.debug(f"Cluster already summarized: {cluster_key[:30]}...")
                self.stats["processed"] += 1
                return True

            logger.info(
                f"Found cluster of {len(similar)+1} articles for: {headline[:40]}..."
            )

            # Get full article data
            all_ids = [doc_id] + [s["id"] for s in similar[:4]]
            articles = self.cluster_detector.get_cluster_articles(all_ids)

            # Generate summary
            summary = self.summarizer.summarize_cluster(articles)

            if summary:
                self._summarized_clusters.add(cluster_key)
                self.stats["summaries_generated"] += 1

                # Publish cluster summary
                cluster_data = {
                    "cluster_id": cluster_key,
                    "trigger_article": headline,
                    "trigger_url": url,
                    "cluster_size": len(similar) + 1,
                    "summary": summary,
                    "article_ids": json.dumps(all_ids),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

                self.producer.publish(
                    stream="stream:cluster-summaries",
                    message=cluster_data,
                )

                logger.info(f"Generated summary for cluster of {len(similar)+1} articles")

            self.stats["processed"] += 1
            return True

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return False

    def run(self):
        logger.info("Starting Analyst Service")

        if not self.wait_for_dependencies():
            logger.error("Dependencies not available")
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
            self.consumer.close()
            self.producer.close()
            self.summarizer.close()


def main():
    AnalystService().run()


if __name__ == "__main__":
    main()
