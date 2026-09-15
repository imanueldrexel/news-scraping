from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import OllamaEmbeddings
from langchain.schema import Document
from typing import List
from datetime import datetime
import logging

from newscrawler.core.constants import VECTOR_DB_NAME, MODEL_NAME, EMBEDDING_MODEL_NAME
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FAISSDatasource:
    def __init__(self):
        self.vector_db_name = VECTOR_DB_NAME
        self.model_name = MODEL_NAME
        self.embedding_model_name = EMBEDDING_MODEL_NAME
        self.vectorstore = VECTOR_DB_NAME
        self.embedding_model = OllamaEmbeddings(base_url='http://localhost:11434', model=self.embedding_model_name) #'http://100.80.153.21:11434', model=self.model_name

    def save(self, documents: list[NewsDetailsDTO]) -> List[int]:
        try:
            if self.vector_db_name:
                logger.info(f"Loading existing FAISS vector store from {self.vector_db_name}...")
                self.vectorstore = self._load_vectorstore()
            else:
                dummy_doc = Document(page_content="init", metadata={})
                self.vectorstore = FAISS.from_documents([dummy_doc], self.embedding_model)
                self.vectorstore.index.reset()
                self.vectorstore.docstore._dict.clear()
                self.vectorstore.index_to_docstore_id.clear()

            # Get existing sitemap_ids at the start
            existing_sitemap_ids = self.get_existing_sitemap_ids()

            print(f"There are {len(existing_sitemap_ids)} existing sitemap IDs.")

            new_articles, embedded_sitemap_ids, failed_docs = self.prepare_new_articles(documents, existing_sitemap_ids)

            if new_articles:
                try:
                    logger.info(f"Embedding {len(new_articles)} new articles....")

                    self.vectorstore.add_documents(new_articles)
                    self.vectorstore.save_local(self.vector_db_name)
                    logger.info(f"Saved {len(new_articles)} documents to FAISS vector store.")
                except Exception as e:
                    logger.error(f"Failed to save documents to FAISS vector store: {e}")
                    failed_docs.extend(new_articles)

            if failed_docs:
                logger.warning(f"{len(failed_docs)} documents failed to embed or save. See logs for details.")

            if embedded_sitemap_ids:
                return embedded_sitemap_ids
        except Exception as e:
            logger.error(f"Critical failure in save: {e}")
            raise e
        

    def _load_vectorstore(self):
        try:
            return FAISS.load_local(
                self.vector_db_name,
                self.embedding_model,
                allow_dangerous_deserialization=True
            )
        except RuntimeError as e:
            logger.warning(f"Failed to load vector store from {self.vector_db_name}: {e}. Creating a new one.")
            # Initialize empty
            dummy_doc = Document(page_content="init", metadata={})
            vectorstore = FAISS.from_documents([dummy_doc], self.embedding_model)
            # Reset immediately
            vectorstore.index.reset()
            vectorstore.docstore._dict.clear()
            vectorstore.index_to_docstore_id.clear()
            return vectorstore

    def get_existing_sitemap_ids(self):
        """Return a set of sitemap_id values already embedded in the FAISS index."""
        if not hasattr(self.vectorstore, "docstore"):
            self.vectorstore = self._load_vectorstore()
        return set(
            doc.metadata.get("sitemap_id")
            for doc in self.vectorstore.docstore._dict.values()
            if doc.metadata.get("sitemap_id") is not None
        )

    @staticmethod
    def prepare_new_articles(documents, existing_sitemap_ids):
        """
        Prepare new articles for embedding with Standardized Date Metadata.
        Returns (new_articles, embedded_sitemap_ids, failed_docs)
        """
        failed_docs = []
        new_articles = []
        embedded_sitemap_ids = []

        logger.info("MLE Agent: Standardizing metadata and preparing documents...")

        for idx, document in enumerate(documents, 1):
            sitemap_id = document.sitemap_id
            if sitemap_id in existing_sitemap_ids:
                continue  # Skip already embedded

            try:
                # --- 1. Content Engineering (Add Title to Content) ---
                # Adding the title to the vector text improves search accuracy significantly.
                raw_text = " ".join(document.extracted_text) if isinstance(document.extracted_text, list) else document.extracted_text
                title = document.meta_data.get("title", "")
                page_content = f"{title}\n\n{raw_text}"

                # --- 2. Date Standardization (CRITICAL) ---
                # We must ensure 'posted_at' is a string in ISO format (YYYY-MM-DD...)
                # so the retriever can parse it easily later.
                raw_date = document.meta_data.get("posted_at")
                clean_date_str = ""

                if raw_date:
                    if isinstance(raw_date, datetime):
                        clean_date_str = raw_date.isoformat()
                    elif isinstance(raw_date, str):
                        # Ideally, ensure this string is ISO. If it's "Senin, 10 Jan", 
                        # you might need a custom parser here.
                        # For now, we assume it's parseable or already ISO.
                        clean_date_str = raw_date
                
                # If no date found, you might want to log a warning or use datetime.now()
                if not clean_date_str:
                    logger.warning(f"No date found for doc {sitemap_id}, skipping time filter capability.")

                article = Document(
                    page_content=page_content,
                    metadata={
                        "title": title,
                        "posted_at": clean_date_str, # <--- Standardized Key
                        "sitemap_id": sitemap_id,
                        "source": document.meta_data.get("url") # Useful for citations
                    }
                )
                new_articles.append(article)
                embedded_sitemap_ids.append(sitemap_id)

            except Exception as e:
                logger.error(f"Failed to prepare document idx={idx}: {e}")
                failed_docs.append(document)
                continue

        return new_articles, embedded_sitemap_ids, failed_docs