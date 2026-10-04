"""DBT-02 (#21): a newsletter run embeds with the MiniLM the FAISS datasource
already loaded, not with a second SentenceTransformer of the same model."""
from unittest.mock import MagicMock, patch

import numpy as np

from newscrawler.core.newsletter_generator import NewsletterGenerator


def test_an_injected_embedder_is_used_and_no_model_is_loaded():
    embed = MagicMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
    gen = NewsletterGenerator(MagicMock(), summarizer=None, embed_documents=embed)
    with patch("sentence_transformers.SentenceTransformer", side_effect=AssertionError("second model load")):
        vectors = gen._encode(["a", "b"])
    embed.assert_called_once_with(["a", "b"])
    assert isinstance(vectors, np.ndarray) and vectors.shape == (2, 2)


def test_the_pipeline_wires_the_faiss_model_into_the_newsletter():
    from newscrawler.infrastructure.repositories.dataflow import data_flow_repository_impl as impl
    faiss_ds = MagicMock()
    with patch.object(impl, "ChunkFAISSDatasource", return_value=faiss_ds), \
         patch.object(impl, "NewsDataSource"), patch.object(impl, "SQLAlchemyChunkDataSource"), \
         patch.object(impl, "SQLAlchemyKnowledgeDataSource"), patch.object(impl, "KnowledgeExtractor"), \
         patch.object(impl, "SQLAlchemyNewsletterDataSource"):
        repo = impl.DataFlowRepositoryImpl(MagicMock())
    assert repo.newsletter_generator._embed_documents is faiss_ds.embedding_model.embed_documents
