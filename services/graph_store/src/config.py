"""Configuration for Graph Store."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class GraphStoreSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    input_stream: str = "stream:entities"
    consumer_group: str = "group:graph-store"
    consumer_name: str = "graph-store-1"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"
    batch_size: int = 10
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> GraphStoreSettings:
    return GraphStoreSettings()
