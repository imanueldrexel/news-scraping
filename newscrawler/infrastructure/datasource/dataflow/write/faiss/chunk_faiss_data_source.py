import logging
import os
from typing import List

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2, EMBEDDING_MODEL_HF
from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO

logger = logging.getLogger(__name__)


class ChunkFAISSDatasource:
    def __init__(self):
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_HF}")
        self.embedding_model = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_HF,
            encode_kwargs={'batch_size': 64, 'normalize_embeddings': True},
        )
        self.vs_l1 = self._load_or_create(VECTOR_DB_NAME_L1)
        self.vs_l2 = self._load_or_create(VECTOR_DB_NAME_L2)
        logger.info("ChunkFAISSDatasource ready (L1 + L2 indexes loaded)")

    def save(self, chunks: List[ChunkDTO]) -> List[ChunkDTO]:
        """Embed chunks into L1/L2 FAISS indexes. Returns chunks with embedding_id populated."""
        l1_chunks = [c for c in chunks if c.chunk_level == 1]
        l2_chunks = [c for c in chunks if c.chunk_level == 2]

        updated: List[ChunkDTO] = []
        if l1_chunks:
            updated.extend(self._embed_batch(l1_chunks, self.vs_l1, VECTOR_DB_NAME_L1))
        if l2_chunks:
            updated.extend(self._embed_batch(l2_chunks, self.vs_l2, VECTOR_DB_NAME_L2))
        return updated

    def _embed_batch(self, chunks: List[ChunkDTO], vs: FAISS, db_name: str) -> List[ChunkDTO]:
        existing_ids = self._get_existing_sitemap_ids(vs)
        new_chunks = [c for c in chunks if c.sitemap_id not in existing_ids]
        already_done = [c for c in chunks if c.sitemap_id in existing_ids]

        if not new_chunks:
            logger.info(f"  {db_name}: all {len(chunks)} chunks already embedded, skipping")
            return already_done

        docs = [self._to_document(c) for c in new_chunks]
        embedding_ids = vs.add_documents(docs)  # LangChain returns list of UUID strings
        vs.save_local(db_name)
        logger.info(f"  {db_name}: embedded {len(new_chunks)} new chunks")

        # Attach embedding_ids back to the chunk objects
        result = list(already_done)
        for chunk, eid in zip(new_chunks, embedding_ids):
            result.append(ChunkDTO(
                sitemap_id=chunk.sitemap_id,
                chunk_level=chunk.chunk_level,
                chunk_index=chunk.chunk_index,
                chunk_total=chunk.chunk_total,
                is_first_chunk=chunk.is_first_chunk,
                is_last_chunk=chunk.is_last_chunk,
                text_content=chunk.text_content,
                token_count=chunk.token_count,
                title=chunk.title,
                source=chunk.source,
                category=chunk.category,
                posted_at=chunk.posted_at,
                reporter=chunk.reporter,
                chunk_id=chunk.chunk_id,
                embedding_id=eid,
                chunk_status='embedded',
            ))
        return result

    def _to_document(self, chunk: ChunkDTO) -> Document:
        return Document(
            page_content=chunk.text_content,
            metadata={
                'sitemap_id': chunk.sitemap_id,
                'chunk_level': chunk.chunk_level,
                'chunk_index': chunk.chunk_index,
                'title': chunk.title,
                'source': chunk.source,
                'category': chunk.category or '',
                'posted_at': str(chunk.posted_at or ''),
            },
        )

    def _load_or_create(self, db_name: str) -> FAISS:
        index_path = os.path.join(db_name, "index.faiss")
        if os.path.exists(index_path):
            logger.info(f"Loading existing FAISS index: {db_name}")
            return FAISS.load_local(db_name, self.embedding_model, allow_dangerous_deserialization=True)

        logger.info(f"Creating new FAISS index: {db_name}")
        dummy = Document(page_content="init", metadata={})
        vs = FAISS.from_documents([dummy], self.embedding_model)
        vs.index.reset()
        vs.docstore._dict.clear()
        vs.index_to_docstore_id.clear()
        return vs

    def search_l2(self, query_text: str, k: int = 20) -> List[dict]:
        """Semantic search against the L2 (paragraph) index. Returns top-k hits."""
        try:
            results = self.vs_l2.similarity_search_with_score(query_text, k=k)
        except Exception as e:
            logger.warning(f"FAISS search failed: {e}")
            return []

        hits = []
        for doc, score in results:
            # similarity_search_with_score returns an L2 distance (lower = more similar)
            # under DistanceStrategy.EUCLIDEAN_DISTANCE. Embeddings are unit-normalized,
            # so distance d maps to cosine similarity via cos = 1 - d^2 / 2. Convert here
            # so downstream ranking can treat semantic_score as "higher = more relevant".
            distance = float(score)
            semantic_score = max(0.0, 1.0 - (distance * distance) / 2.0)
            hits.append({
                "text_content": doc.page_content,
                "semantic_score": semantic_score,
                "sitemap_id":  doc.metadata.get("sitemap_id"),
                "source":      doc.metadata.get("source", ""),
                "posted_at":   doc.metadata.get("posted_at", ""),
                "title":       doc.metadata.get("title", ""),
                "category":    doc.metadata.get("category", ""),
                "chunk_level": doc.metadata.get("chunk_level"),
            })
        return hits

    @staticmethod
    def _get_existing_sitemap_ids(vs: FAISS) -> set:
        return {
            int(doc.metadata['sitemap_id'])
            for doc in vs.docstore._dict.values()
            if 'sitemap_id' in doc.metadata
        }
