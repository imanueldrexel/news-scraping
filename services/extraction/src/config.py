"""Configuration for Extraction Engine."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class ExtractionSettings(BaseSettings):
    """Extraction engine specific settings."""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Streams
    input_stream: str = "stream:preprocessed"
    output_stream: str = "stream:triplets"

    # Consumer group
    consumer_group: str = "group:extraction"
    consumer_name: str = "extraction-1"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_timeout: float = 120.0  # seconds

    # Processing
    batch_size: int = 5
    max_chunks_per_article: int = 5  # Limit chunks to process per article
    min_confidence: float = 0.5  # Minimum confidence for triplets

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> ExtractionSettings:
    return ExtractionSettings()
