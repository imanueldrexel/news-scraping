from datetime import date
from typing import Dict, List, Optional, Tuple, Union

from newscrawler.core.constants import KNOWLEDGE_BATCH_SIZE
from newscrawler.core.knowledge_extractor import KnowledgeExtractor
from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.infrastructure.datasource.dataflow.model.chunk_model import ChunkModel
from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsSitemapModel,
)
from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import (
    NewsDataSource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_chunk_data_source import SQLAlchemyChunkDataSource
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import SQLAlchemyKnowledgeDataSource
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import SQLAlchemyNewsletterDataSource
from newscrawler.core.newsletter_generator import NewsletterGenerator


class DataFlowRepositoryImpl(DataFlowRepository):
    def __init__(self, sql_alchemy_client):
        self.news_data_source             = NewsDataSource(sql_alchemy_client)
        self.chunk_faiss_datasource       = ChunkFAISSDatasource()
        self.sql_alchemy_chunk_datasource = SQLAlchemyChunkDataSource(sql_alchemy_client)
        self.knowledge_datasource         = SQLAlchemyKnowledgeDataSource(sql_alchemy_client)
        self.knowledge_extractor          = KnowledgeExtractor(self.knowledge_datasource)
        self.newsletter_datasource        = SQLAlchemyNewsletterDataSource(sql_alchemy_client)
        self.newsletter_generator         = NewsletterGenerator(self.newsletter_datasource)

    def load_sitemap_data(self, website: str, n_limit: int) -> List[NewsDetailsDTO]:
        news_sitemap_model =  self.news_data_source.load_sitemap(website=website, n_limit=n_limit)
        news_sitemap_dto = [self._to_sitemap_dto(news) for news in news_sitemap_model]
        return news_sitemap_dto

    def save_sitemap_data(self, sitemaps: List[NewsDetailsDTO]) -> List[SitemapDTO]:
        news_sitemap_model = self.to_news_information_model(sitemaps)
        saved_models = self.news_data_source.save_sitemap(news_sitemap_model)
        return [self._to_sitemap_dto(m) for m in saved_models] if saved_models else []

    def save_newsdetails_data(self, newsdetails: List[NewsDetailsDTO]):
        newsdetail_model = self.to_news_information_model(newsdetails)
        self.news_data_source.save_newsdetails(newsdetail_model)

    def save_chunk_data(self, chunks: List[ChunkDTO]) -> List[int]:
        chunks_with_ids = self.chunk_faiss_datasource.save(chunks)
        # Persist only newly-embedded chunks to SQL. Chunks whose sitemap was already
        # embedded in a prior run come back with embedding_id=None and already have rows
        # in the chunks table -- re-inserting them would create duplicates.
        new_models = [self._to_chunk_model(c) for c in chunks_with_ids if c.embedding_id]
        self.sql_alchemy_chunk_datasource.save_chunks(new_models)
        # Return ALL represented sitemap_ids (newly embedded AND already embedded) so the
        # caller still saves the article row for already-embedded sitemaps. Filtering on
        # embedding_id here used to strand already-embedded sitemaps without an article.
        return list({c.sitemap_id for c in chunks_with_ids})

    def mark_sitemaps_attempted(self, sitemap_ids: List[int]) -> None:
        self.news_data_source.mark_sitemaps_attempted(sitemap_ids)

    @staticmethod
    def _to_chunk_model(chunk: ChunkDTO) -> ChunkModel:
        return ChunkModel(
            sitemap_id=chunk.sitemap_id,
            chunk_level=chunk.chunk_level,
            chunk_index=chunk.chunk_index,
            chunk_total=chunk.chunk_total,
            is_first_chunk=chunk.is_first_chunk,
            is_last_chunk=chunk.is_last_chunk,
            text_content=chunk.text_content,
            token_count=chunk.token_count,
            embedding_id=chunk.embedding_id,
            chunk_status=chunk.chunk_status,
        )

    def to_news_information_model(
        self, news_information: List[Union[NewsDetailsDTO, SitemapDTO]]
    ) -> List[Union[NewsSitemapModel, NewsDetailsModel]]:
        if isinstance(news_information[0], SitemapDTO):
            sitemap_model = [
                self._to_sitemap_data_model(news) for news in news_information
            ]
            return sitemap_model
        elif isinstance(news_information[0], NewsDetailsDTO):
            newsdetail_model = [
                self._to_newsdetail_data_model(news) for news in news_information
            ]
            return newsdetail_model

    @staticmethod
    def _to_sitemap_data_model(
        sitemap_detail: SitemapDTO,
    ) -> NewsSitemapModel:
        return NewsSitemapModel(
            headline=sitemap_detail.headline,
            link=sitemap_detail.link,
            sources=sitemap_detail.sources,
            category=sitemap_detail.category,
            posted_at=sitemap_detail.timestamp,
            keywords=sitemap_detail.keywords,
            sitemap_id=getattr(sitemap_detail, "sitemap_id", None),  # Pass id if present
        )

    @staticmethod
    def _to_sitemap_dto(
        sitemap_model: NewsSitemapModel,
    ) -> SitemapDTO:
        return SitemapDTO(
            headline=sitemap_model.headline,
            link=sitemap_model.link,
            sources=sitemap_model.sources,
            category=sitemap_model.category,
            timestamp=sitemap_model.posted_at,
            keywords=sitemap_model.keywords,
            sitemap_id=getattr(sitemap_model, "sitemap_id", None),  # Pass id if present
        )

    @staticmethod
    def _to_newsdetail_data_model(
        news_details: NewsDetailsDTO,
    ) -> NewsDetailsModel:
        meta_data = dict(news_details.meta_data) if news_details.meta_data else {}
        posted_at = meta_data.get('posted_at')

        if posted_at is not None and not isinstance(posted_at, int):
            try:
                # Convert to int in yyyyMMdd format if not already int
                meta_data['posted_at'] = int(posted_at.strftime('%Y%m%d'))
            except Exception:
                meta_data.pop('posted_at', None)

        return NewsDetailsModel(
            sitemap_id=news_details.sitemap_id,
            extracted_text=news_details.extracted_text,
            reporter=news_details.reporter,
            meta_data=meta_data,
            is_embedded=True
        )

    # ── Knowledge extraction (Phase 2) ───────────────────────────────────────

    def extract_knowledge(self, batch_size: Optional[int] = None) -> int:
        return self.knowledge_extractor.extract_all()

    def load_entities_for_query(
        self,
        entity_name: Optional[str] = None,
        ticker: Optional[str] = None,
        days: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        event_type: Optional[str] = None,
    ) -> dict:
        return self.knowledge_datasource.query_entity_mentions(
            entity_name=entity_name,
            ticker=ticker,
            days=days,
            from_date=from_date,
            to_date=to_date,
            event_type=event_type,
        )

    def seed_entity_aliases(self, seed_data: list) -> None:
        self.knowledge_datasource.seed_aliases(seed_data)

    def generate_newsletter(self, target_date=None):
        return self.newsletter_generator.generate(target_date)

    def get_stats(self) -> dict:
        return self.newsletter_datasource.get_stats()

    def log_crawl_start(self, website: str, task: str) -> Optional[int]:
        return self.news_data_source.sql_alchemy_article.log_crawl_start(website, task)

    def log_crawl_complete(self, log_id: Optional[int], article_count: int = 0) -> None:
        self.news_data_source.sql_alchemy_article.log_crawl_complete(log_id, article_count)

    def log_crawl_failed(self, log_id: Optional[int], error_msg: str) -> None:
        self.news_data_source.sql_alchemy_article.log_crawl_failed(log_id, error_msg)
