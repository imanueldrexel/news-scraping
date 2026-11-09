"""ChromaDB client for vector storage and search."""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


class ChromaDBClient:
    """
    Client for ChromaDB vector database.
    Handles document storage and similarity search.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        collection_name: str = "indonesian_news",
    ):
        """
        Initialize ChromaDB client.

        Args:
            host: ChromaDB server host
            port: ChromaDB server port
            collection_name: Name of the collection to use
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self._client: Optional[chromadb.HttpClient] = None
        self._collection = None

    @property
    def client(self) -> chromadb.HttpClient:
        """Lazy initialize ChromaDB client."""
        if self._client is None:
            self._client = chromadb.HttpClient(
                host=self.host,
                port=self.port,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client

    @property
    def collection(self):
        """Get or create collection."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    "description": "Indonesian news article embeddings",
                },
            )
        return self._collection

    def add_document(
        self,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """
        Add a document to the collection.

        Args:
            doc_id: Unique document ID
            embedding: Embedding vector
            text: Document text (for storage)
            metadata: Document metadata
        """
        try:
            # Ensure metadata values are JSON serializable
            clean_metadata = {}
            for key, value in metadata.items():
                if value is None:
                    clean_metadata[key] = ""
                elif isinstance(value, datetime):
                    clean_metadata[key] = value.isoformat()
                elif isinstance(value, (list, dict)):
                    import json

                    clean_metadata[key] = json.dumps(value)
                else:
                    clean_metadata[key] = str(value)

            self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[clean_metadata],
            )
            logger.debug(f"Added document {doc_id}")

        except Exception as e:
            logger.error(f"Failed to add document {doc_id}: {e}")
            raise

    def add_documents_batch(
        self,
        doc_ids: List[str],
        embeddings: List[List[float]],
        texts: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """
        Add multiple documents in batch.

        Args:
            doc_ids: List of document IDs
            embeddings: List of embedding vectors
            texts: List of document texts
            metadatas: List of metadata dicts
        """
        try:
            # Clean metadata
            clean_metadatas = []
            for metadata in metadatas:
                clean = {}
                for key, value in metadata.items():
                    if value is None:
                        clean[key] = ""
                    elif isinstance(value, datetime):
                        clean[key] = value.isoformat()
                    elif isinstance(value, (list, dict)):
                        import json

                        clean[key] = json.dumps(value)
                    else:
                        clean[key] = str(value)
                clean_metadatas.append(clean)

            self.collection.add(
                ids=doc_ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=clean_metadatas,
            )
            logger.info(f"Added {len(doc_ids)} documents in batch")

        except Exception as e:
            logger.error(f"Failed to add batch: {e}")
            raise

    def query_similar(
        self,
        embedding: List[float],
        n_results: int = 10,
        threshold: float = 0.0,
        where: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Query for similar documents.

        Args:
            embedding: Query embedding vector
            n_results: Maximum number of results
            threshold: Minimum similarity threshold (0-1)
            where: Optional filter conditions

        Returns:
            List of similar documents with metadata
        """
        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=["metadatas", "documents", "distances"],
            )

            similar = []
            for i, distance in enumerate(results["distances"][0]):
                # Convert distance to similarity (cosine distance)
                similarity = 1 - distance

                if similarity >= threshold:
                    similar.append(
                        {
                            "id": results["ids"][0][i],
                            "document": results["documents"][0][i],
                            "metadata": results["metadatas"][0][i],
                            "similarity": similarity,
                        }
                    )

            return similar

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def document_exists(self, doc_id: str) -> bool:
        """
        Check if a document exists.

        Args:
            doc_id: Document ID to check

        Returns:
            True if document exists
        """
        try:
            result = self.collection.get(ids=[doc_id])
            return len(result["ids"]) > 0
        except Exception:
            return False

    def get_document(self, doc_id: str) -> Optional[Dict]:
        """
        Get a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document dict or None
        """
        try:
            result = self.collection.get(
                ids=[doc_id],
                include=["metadatas", "documents"],
            )
            if result["ids"]:
                return {
                    "id": result["ids"][0],
                    "document": result["documents"][0],
                    "metadata": result["metadatas"][0],
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get document {doc_id}: {e}")
            return None

    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if deleted
        """
        try:
            self.collection.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False

    def get_collection_stats(self) -> Dict:
        """Get collection statistics."""
        try:
            count = self.collection.count()
            return {
                "collection_name": self.collection_name,
                "document_count": count,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}

    def is_available(self) -> bool:
        """Check if ChromaDB is available."""
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False
