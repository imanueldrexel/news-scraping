"""Configuration for Preprocessor Service."""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class PreprocessorSettings(BaseSettings):
    """Preprocessor service specific settings."""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Streams
    input_stream: str = "stream:ingested"
    output_stream: str = "stream:preprocessed"

    # Consumer group
    consumer_group: str = "group:preprocessor"
    consumer_name: str = "preprocessor-1"

    # Chunking
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 50  # tokens

    # Relevance
    relevance_threshold: float = 0.35
    use_semantic_filter: bool = True

    # Batch processing
    batch_size: int = 10

    # Logging
    log_level: str = "INFO"

    # Indonesian interests for relevance filtering
    interests: List[str] = [
        "pasar saham",
        "keuangan",
        "ekonomi",
        "makroekonomi",
        "mikroekonomi",
        "inflasi",
        "suku bunga",
        "kebijakan bank sentral",
        "pertumbuhan PDB",
        "laporan keuangan",
        "investasi",
        "komoditas",
        "forex",
        "IHSG",
        "rupiah",
        "obligasi",
        "saham",
        "dividen",
        "IPO",
        "merger",
        "akuisisi",
    ]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> PreprocessorSettings:
    return PreprocessorSettings()
