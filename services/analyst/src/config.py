"""Configuration for Analyst Service."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class AnalystSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    input_stream: str = "stream:vectorized"
    consumer_group: str = "group:analyst"
    consumer_name: str = "analyst-1"
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    similarity_threshold: float = 0.85
    min_cluster_size: int = 2
    batch_size: int = 10
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> AnalystSettings:
    return AnalystSettings()
