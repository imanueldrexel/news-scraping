from datetime import date
from typing import Dict, List, Optional, Set, Tuple, Union

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
    SitemapSaveResult,
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
        dtos = [self._to_sitemap_dto(m) for m in saved_models] if saved_models else []
        # SYS-07: carry the new-vs-existing count across the DTO conversion (a plain
        # list comprehension would otherwise drop it) so crawl_log.article_count can
        # reflect real new-row counts.
        return SitemapSaveResult(dtos, new_count=getattr(saved_models, "new_count", len(dtos)))

    def save_newsdetails_data(self, newsdetails: List[NewsDetailsDTO]) -> List[int]:
        newsdetail_model = self.to_news_information_model(newsdetails)
        return self.news_data_source.save_newsdetails(newsdetail_model)

    def save_chunk_data(self, chunks: List[ChunkDTO]) -> List[int]:
        if not chunks:
            return []
        all_sitemap_ids = {c.sitemap_id for c in chunks}
        # SYS-17: dedup against SQL (the source of truth for "do chunks rows exist"),
        # not FAISS membership. FAISS is written to disk before the SQL commit; if
        # that commit then fails (or is skipped for any reason), FAISS keeps the
        # vectors and the chunks table has nothing -- treating FAISS membership as
        # "already saved" made that permanent, since every later attempt saw the
        # vectors and skipped the SQL insert again.
        #
        # SYS-25: the dedup key is (sitemap_id, chunk_level), not sitemap_id alone.
        # A sitemap can hold chunks at one level and be missing the other (a partial
        # prior write); keying on sitemap_id alone treated it as fully saved and
        # permanently dropped the missing level from `to_process` on every retry.
        # Everything not already represented goes through chunk_faiss_datasource
        # .save(), which still checks FAISS on its own (keyed on
        # sitemap_id+level+index) to avoid adding duplicate vectors and to recover
        # the *real* embedding_id for anything already embedded there.
        already_saved_pairs = self.sql_alchemy_chunk_datasource.get_existing_sitemap_level_pairs(all_sitemap_ids)
        to_process = [c for c in chunks if (c.sitemap_id, c.chunk_level) not in already_saved_pairs]

        if to_process:
            chunks_with_ids = self.chunk_faiss_datasource.save(to_process)
            new_models = [self._to_chunk_model(c) for c in chunks_with_ids]
            self.sql_alchemy_chunk_datasource.save_chunks(new_models)

        return list(all_sitemap_ids)

    def mark_sitemaps_attempted(self, sitemap_ids: List[int]) -> None:
        self.news_data_source.mark_sitemaps_attempted(sitemap_ids)

    def mark_sitemaps_status(self, sitemap_ids: List[int], status: str) -> None:
        self.news_data_source.mark_sitemaps_status(sitemap_ids, status)

    def increment_fetch_failures(self, sitemap_ids: List[int], error_msg: str = None) -> None:
        self.news_data_source.increment_fetch_failures(sitemap_ids, error_msg)

    def get_saved_category_pairs(self, website: str) -> Set[Tuple[str, str]]:
        return self.news_data_source.get_saved_category_pairs(website)

    def update_sitemap_headlines(self, headlines_by_id: Dict[int, str]) -> int:
        return self.news_data_source.update_sitemap_headlines(headlines_by_id)

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
