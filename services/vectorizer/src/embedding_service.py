"""Embedding service using Ollama."""

import httpx
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class OllamaEmbeddingService:
    """
    Generates embeddings using Ollama's embedding models.
    Uses nomic-embed-text by default.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: float = 60.0,
    ):
        """
        Initialize embedding service.

        Args:
            base_url: Ollama API base URL
            model: Embedding model name
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Lazy initialize HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def embed(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        try:
            response = self.client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )
            response.raise_for_status()

            result = response.json()
            return result["embedding"]

        except httpx.HTTPError as e:
            logger.error(f"HTTP error generating embedding: {e}")
            raise
        except KeyError as e:
            logger.error(f"Unexpected response format: {e}")
            raise

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.

        Note: Ollama doesn't support batch embedding natively,
        so this processes texts sequentially.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        embeddings = []

        for text in texts:
            try:
                embedding = self.embed(text)
                embeddings.append(embedding)
            except Exception as e:
                logger.warning(f"Failed to embed text: {e}")
                # Return zero vector on failure
                embeddings.append([0.0] * 768)  # nomic-embed-text dimension

        return embeddings

    def is_available(self) -> bool:
        """
        Check if Ollama is available and model is loaded.

        Returns:
            True if service is ready
        """
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False

            models = response.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]

            if self.model not in model_names and f"{self.model}:latest" not in [
                m.get("name") for m in models
            ]:
                logger.warning(
                    f"Model {self.model} not found. Available: {model_names}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Ollama availability check failed: {e}")
            return False

    def pull_model(self) -> bool:
        """
        Pull the embedding model if not available.

        Returns:
            True if model is available after pull
        """
        try:
            logger.info(f"Pulling model {self.model}...")
            response = self.client.post(
                f"{self.base_url}/api/pull",
                json={"name": self.model},
                timeout=300.0,  # 5 minutes for model download
            )
            response.raise_for_status()
            logger.info(f"Model {self.model} pulled successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to pull model: {e}")
            return False

    def close(self):
        """Close HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
