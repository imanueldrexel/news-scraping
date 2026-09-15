"""Cluster detector using ChromaDB similarity search."""

import logging
from typing import List, Dict, Optional
import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


class ClusterDetector:
    """Detects clusters of similar articles using ChromaDB."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        collection_name: str = "indonesian_news",
        similarity_threshold: float = 0.85,
    ):
        self.client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection_name = collection_name
        self.threshold = similarity_threshold
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name
            )
        return self._collection

    def find_similar(
        self,
        doc_id: str,
        n_results: int = 10,
    ) -> List[Dict]:
        """Find articles similar to a given document."""
        try:
            # Get the document's embedding
            result = self.collection.get(
                ids=[doc_id],
                include=["embeddings", "metadatas"],
            )

            if not result["ids"]:
                return []

            embedding = result["embeddings"][0]

            # Query for similar documents
            similar = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results + 1,  # +1 to exclude self
                include=["metadatas", "documents", "distances"],
            )

            cluster = []
            for i, distance in enumerate(similar["distances"][0]):
                similarity = 1 - distance
                sim_id = similar["ids"][0][i]

                # Skip self
                if sim_id == doc_id:
                    continue

                if similarity >= self.threshold:
                    cluster.append({
                        "id": sim_id,
                        "metadata": similar["metadatas"][0][i],
                        "document": similar["documents"][0][i] if similar["documents"] else "",
                        "similarity": similarity,
                    })

            return cluster

        except Exception as e:
            logger.error(f"Error finding similar documents: {e}")
            return []

    def get_cluster_articles(self, doc_ids: List[str]) -> List[Dict]:
        """Get full article data for cluster members."""
        try:
            result = self.collection.get(
                ids=doc_ids,
                include=["metadatas", "documents"],
            )

            articles = []
            for i, doc_id in enumerate(result["ids"]):
                articles.append({
                    "id": doc_id,
                    "metadata": result["metadatas"][i],
                    "text": result["documents"][i] if result["documents"] else "",
                })

            return articles

        except Exception as e:
            logger.error(f"Error getting cluster articles: {e}")
            return []
