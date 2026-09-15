from abc import abstractmethod
from datetime import date
from typing import Dict, List, Optional, Tuple

from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)


class DataFlowRepository:
    @abstractmethod
    def save_sitemap_data(self, sitemaps: List[SitemapDTO]) -> NewsInformationModel:
        raise NotImplementedError

    @abstractmethod
    def save_newsdetails_data(
        self, sitemaps: List[NewsDetailsDTO]
    ) -> NewsInformationModel:
        raise NotImplementedError

    def load_sitemap_data(self, website: str, n_limit: int) -> Dict[str, List[Tuple[int, str]]]:
        raise NotImplementedError

    def save_chunk_data(self, chunks: List[ChunkDTO]) -> List[int]:
        raise NotImplementedError

    def mark_sitemaps_attempted(self, sitemap_ids: List[int]) -> None:
        raise NotImplementedError

    def extract_knowledge(self, batch_size: Optional[int] = None) -> int:
        raise NotImplementedError

    def load_entities_for_query(
        self,
        entity_name: Optional[str] = None,
        ticker: Optional[str] = None,
        days: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        event_type: Optional[str] = None,
    ) -> dict:
        raise NotImplementedError

    def seed_entity_aliases(self, seed_data: list) -> None:
        raise NotImplementedError

    def generate_newsletter(self, target_date=None) -> Optional[str]:
        raise NotImplementedError

    def get_stats(self) -> dict:
        raise NotImplementedError

    def log_crawl_start(self, website: str, task: str) -> Optional[int]:
        return None

    def log_crawl_complete(self, log_id: Optional[int], article_count: int = 0) -> None:
        pass

    def log_crawl_failed(self, log_id: Optional[int], error_msg: str) -> None:
        pass