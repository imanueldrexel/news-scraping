
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure the project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source import FAISSDatasource
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from langchain.schema import Document

class TestFAISSDatasource(unittest.TestCase):

    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.FAISS')
    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.OllamaEmbeddings')
    def test_save_new_documents(self, mock_ollama, mock_faiss):
        # Setup mocks
        mock_vectorstore = MagicMock()
        mock_faiss.load_local.return_value = mock_vectorstore
        # Mocking docstore to simulate existing IDs (empty initially)
        mock_vectorstore.docstore._dict = {}
        
        datasource = FAISSDatasource()
        # Force vectorstore to be our mock, although load_local might be called inside save
        # in save() it calls _load_vectorstore() if vector_db_name is set.
        # Let's ensure _load_vectorstore returns our mock.
        datasource._load_vectorstore = MagicMock(return_value=mock_vectorstore)

        # Create dummy documents with updated metadata structure
        from datetime import datetime
        documents = [
            NewsDetailsDTO(
                sitemap_id=1,
                extracted_text=["Content 1"],
                reporter=None,
                meta_data={"title": "Title 1", "posted_at": datetime(2023, 1, 1), "url": "https://example.com/1"}
            ),
            NewsDetailsDTO(
                sitemap_id=2,
                extracted_text=["Content 2"],
                reporter=None,
                meta_data={"title": "Title 2", "posted_at": "2023-01-02", "url": "https://example.com/2"}
            )
        ]

        # Call save
        result = datasource.save(documents)

        # Verification
        self.assertEqual(len(result), 2)
        self.assertIn(1, result)
        self.assertIn(2, result)
        
        # Verify add_documents was called
        self.assertTrue(mock_vectorstore.add_documents.called)
        args, _ = mock_vectorstore.add_documents.call_args
        added_docs = args[0]
        self.assertEqual(len(added_docs), 2)
        
        # Verify new metadata structure
        self.assertEqual(added_docs[0].metadata['sitemap_id'], 1)
        self.assertEqual(added_docs[1].metadata['sitemap_id'], 2)
        
        # Verify title is prepended to page_content
        self.assertIn("Title 1", added_docs[0].page_content)
        self.assertIn("Content 1", added_docs[0].page_content)
        
        # Verify standardized date (should be ISO string)
        self.assertIsInstance(added_docs[0].metadata['posted_at'], str)
        
        # Verify source field exists
        self.assertEqual(added_docs[0].metadata.get('source'), "https://example.com/1")
        
        # Verify save_local was called
        self.assertTrue(mock_vectorstore.save_local.called)


    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.FAISS')
    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.OllamaEmbeddings')
    def test_save_existing_documents(self, mock_ollama, mock_faiss):
        # Setup mocks
        mock_vectorstore = MagicMock()
        datasource = FAISSDatasource()
        datasource._load_vectorstore = MagicMock(return_value=mock_vectorstore)

        # Simulate existing document in docstore
        existing_doc = Document(page_content="Old", metadata={"sitemap_id": 1})
        mock_vectorstore.docstore._dict = {'uuid1': existing_doc}
        
        # Create documents, one existing, one new (with updated metadata structure)
        from datetime import datetime
        documents = [
            NewsDetailsDTO(
                sitemap_id=1,
                extracted_text=["Content 1"],
                reporter=None,
                meta_data={"title": "Title 1", "posted_at": datetime(2023, 1, 1), "url": "https://example.com/1"}
            ),
            NewsDetailsDTO(
                sitemap_id=3,
                extracted_text=["Content 3"],
                reporter=None,
                meta_data={"title": "Title 3", "posted_at": "2023-01-03", "url": "https://example.com/3"}
            )
        ]

        # Call save
        result = datasource.save(documents)

        # Verification
        # Should only return the NEW sitemap_id
        self.assertEqual(len(result), 1)
        self.assertIn(3, result)
        self.assertNotIn(1, result)

        # Verify add_documents was called only with the new document
        args, _ = mock_vectorstore.add_documents.call_args
        added_docs = args[0]
        self.assertEqual(len(added_docs), 1)
        self.assertEqual(added_docs[0].metadata['sitemap_id'], 3)
        
        # Verify title in page_content and source in metadata
        self.assertIn("Title 3", added_docs[0].page_content)
        self.assertEqual(added_docs[0].metadata.get('source'), "https://example.com/3")

    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.FAISS')
    @patch('newscrawler.infrastructure.datasource.dataflow.write.faiss.faiss_news_data_source.OllamaEmbeddings')
    def test_get_existing_sitemap_ids(self, mock_ollama, mock_faiss):
        # Setup mocks
        mock_vectorstore = MagicMock()
        datasource = FAISSDatasource()
        datasource.vectorstore = mock_vectorstore

        # Simulate existing documents
        doc1 = Document(page_content="1", metadata={"sitemap_id": 100})
        doc2 = Document(page_content="2", metadata={"sitemap_id": 200})
        # Some docs might not have sitemap_id (legacy or other)
        doc3 = Document(page_content="3", metadata={"other": "data"})
        
        mock_vectorstore.docstore._dict = {
            'id1': doc1,
            'id2': doc2,
            'id3': doc3
        }

        ids = datasource.get_existing_sitemap_ids()
        
        self.assertEqual(len(ids), 2)
        self.assertIn(100, ids)
        self.assertIn(200, ids)

if __name__ == '__main__':
    unittest.main()
