"""
Centralized configuration using Pydantic Settings.
All services share this configuration module.
"""

from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # PostgreSQL
    postgres_user: str = "news"
    postgres_password: str = "news123"
    postgres_db: str = "newsdb"
    database_url: str = "postgresql://news:news123@localhost:5432/newsdb"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000

    # Ollama
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    embedding_model: str = "nomic-embed-text"

    # Service Configuration
    polling_interval: int = 300
    relevance_threshold: float = 0.35
    fuzzy_threshold: float = 0.85
    similarity_threshold: float = 0.85

    # Logging
    log_level: str = "INFO"

    # Redis Stream Names
    stream_ingested: str = "stream:ingested"
    stream_preprocessed: str = "stream:preprocessed"
    stream_vectorized: str = "stream:vectorized"
    stream_triplets: str = "stream:triplets"
    stream_entities: str = "stream:entities"

    # Processing Configuration
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 50  # tokens
    batch_size: int = 10
    max_retries: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
