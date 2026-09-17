import logging
import os
from dataclasses import replace
from typing import Dict, List, Tuple

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
        # SYS-17: key on (sitemap_id, chunk_level, chunk_index), not sitemap_id alone,
        # so a chunk already present in FAISS is matched to its *real* embedding_id
        # (the docstore key it was originally added under) instead of being returned
        # with embedding_id=None. This is what makes save_chunk_data's SQL-based
        # dedup (see DataFlowRepositoryImpl.save_chunk_data) self-healing: a sitemap
        # whose SQL insert failed after FAISS already had its vectors gets retried,
        # finds those exact vectors here, and reuses their ids instead of either
        # skipping the SQL insert (the old bug) or adding duplicate vectors.
        existing = self._get_existing_embedding_ids(vs)
        result = []
        new_chunks = []
        seen_this_batch = set()
        for c in chunks:
            key = (c.sitemap_id, c.chunk_level, c.chunk_index)
            if key in existing:
                result.append(replace(c, embedding_id=existing[key], chunk_status='embedded'))
            elif key not in seen_this_batch:
                # DBT-09: existing/seen are the only two sources of truth this method
                # checks. Without seen_this_batch, two chunks sharing a key *within
                # the same call* (a caller passing the same sitemap's chunks twice --
                # e.g. a specific_sitemaps list with a duplicate entry) would both
                # miss `existing` and both get embedded, producing two vectors and
                # two chunks rows for one logical chunk. A later duplicate of an
                # already-queued key is dropped here instead -- one vector, one row.
                seen_this_batch.add(key)
                new_chunks.append(c)

        if not new_chunks:
            logger.info(f"  {db_name}: all {len(chunks)} chunks already embedded, skipping")
            return result

        docs = [self._to_document(c) for c in new_chunks]
        embedding_ids = vs.add_documents(docs)  # LangChain returns list of UUID strings
        vs.save_local(db_name)
        logger.info(f"  {db_name}: embedded {len(new_chunks)} new chunks")

        for chunk, eid in zip(new_chunks, embedding_ids):
            result.append(replace(chunk, embedding_id=eid, chunk_status='embedded'))
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
    def _get_existing_embedding_ids(vs: FAISS) -> Dict[Tuple[int, int, int], str]:
        """Maps (sitemap_id, chunk_level, chunk_index) -> the docstore key (embedding_id)
        it was stored under, for every document already in this index."""
        result = {}
        for doc_id, doc in vs.docstore._dict.items():
            meta = doc.metadata
            if {'sitemap_id', 'chunk_level', 'chunk_index'} <= meta.keys():
                result[(int(meta['sitemap_id']), int(meta['chunk_level']), int(meta['chunk_index']))] = doc_id
        return result
