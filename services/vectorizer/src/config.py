"""Configuration for Vectorizer Service."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class VectorizerSettings(BaseSettings):
    """Vectorizer service specific settings."""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Streams
    input_stream: str = "stream:preprocessed"
    output_stream: str = "stream:vectorized"

    # Consumer group
    consumer_group: str = "group:vectorizer"
    consumer_name: str = "vectorizer-1"

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000
    collection_name: str = "indonesian_news"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"

    # Processing
    batch_size: int = 10

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> VectorizerSettings:
    return VectorizerSettings()
