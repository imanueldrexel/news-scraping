"""Configuration for Entity Resolver."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class EntityResolverSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    input_stream: str = "stream:triplets"
    output_stream: str = "stream:entities"
    consumer_group: str = "group:entity-resolver"
    consumer_name: str = "entity-resolver-1"
    fuzzy_threshold: float = 0.85
    batch_size: int = 10
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> EntityResolverSettings:
    return EntityResolverSettings()
