"""Configuration for Ingestion Service."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class IngestionSettings(BaseSettings):
    """Ingestion service specific settings."""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Database
    database_url: str = "postgresql://news:news123@localhost:5432/newsdb"

    # Polling
    polling_interval: int = 300  # seconds
    max_articles_per_source: int = 100  # per polling cycle

    # Deduplication
    dedup_ttl_days: int = 7  # days to keep URL in dedup cache
    max_article_age_hours: int = 48  # only process articles published within this many hours

    # Output stream
    output_stream: str = "stream:ingested"

    # Parallelization
    max_workers: int = 10
    parallelize: bool = True

    # Logging
    log_level: str = "INFO"

    # Telegram notifications
    telegram_bot_token: str = ""  # Empty = disabled
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> IngestionSettings:
    return IngestionSettings()
