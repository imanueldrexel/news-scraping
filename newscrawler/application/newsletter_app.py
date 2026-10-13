"""The newsletter's own composition root (DBT-74 #346, ADR-017).

`init_crawler()` builds everything a crawl needs: NEWS_L2 (~7.6 GB in memory),
the e5-large news filter (2.2 GB), the knowledge extractor, every crawler. The
12:00 newsletter used it and touched none of those. `build_newsletter_service()`
builds only what the newsletter reads:

- Postgres (the day's articles, the digest row, crawl_log, api_usage_log);
- MiniLM, to embed the day's L1 texts for clustering (the model NEWS_L1 was built with);
- NEWS_L1, loaded read-only through `index_generation.load_index`, as the story
  arcs' `search` (SYS-147). Never saved. `with_l1=False` leaves it out;
- the summarizer, with its calls counted in api_usage_log (ADR-001).

`run_logged` is the one crawl_log bracket around a newsletter run (OPS-11,
SYS-68), shared with `CrawlerServiceImpl.generate_newsletter`.
"""
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def run_logged(repo, target_date=None):
    """Generate the newsletter between crawl_log's start and its completed or
    failed row. `repo` has log_crawl_start/complete/failed and generate_newsletter."""
    logger.info(f"Starting newsletter generation for {target_date or 'today'}...")
    log_id = repo.log_crawl_start("ALL", "newsletter")
    try:
        path = repo.generate_newsletter(target_date)
    except Exception as e:
        repo.log_crawl_failed(log_id, str(e)[:500])
        raise
    # SYS-68 (#216): a digest whose summaries are mostly headlines is
    # complete but degraded; the reason rides on the row (the generator's
    # path carries it as `.note`), so crawl_log says what the file says.
    repo.log_crawl_complete(log_id, 1 if path else 0, note=getattr(path, "note", None))
    logger.info(f"Newsletter generated: {path}")
    return path


class NewsletterRepo:
    """What `run_logged` needs, from the light datasources."""

    def __init__(self, generator, crawl_log):
        self.generator = generator
        self._crawl_log = crawl_log

    def generate_newsletter(self, target_date=None):
        return self.generator.generate(target_date)

    def log_crawl_start(self, website, task):
        return self._crawl_log.log_crawl_start(website, task)

    def log_crawl_complete(self, log_id, article_count=0, note=None):
        self._crawl_log.log_crawl_complete(log_id, article_count, note=note)

    def log_crawl_failed(self, log_id, error_msg):
        self._crawl_log.log_crawl_failed(log_id, error_msg)


class NewsletterService:
    """The `crawler_service` CrawlerAPI calls for task=newsletter."""

    def __init__(self, repo: NewsletterRepo):
        self.repo = repo

    @property
    def generator(self):
        return self.repo.generator

    def generate_newsletter(self, target_date=None):
        return run_logged(self.repo, target_date)


def load_l1_search(embeddings):
    """NEWS_L1, read-only, as thread_finder's `search`."""
    from newscrawler.core.constants import VECTOR_DB_NAME_L1
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
    from newscrawler.infrastructure.datasource.dataflow.write.faiss.l1_search import l1_search
    logger.info(f"Loading {VECTOR_DB_NAME_L1} read-only for the story arcs")
    return l1_search(load_index(VECTOR_DB_NAME_L1, embeddings))


def build_newsletter_service(with_l1: bool = True, client=None) -> NewsletterService:
    from langchain_community.embeddings import HuggingFaceEmbeddings

    from newscrawler.core.constants import EMBEDDING_MODEL_HF
    from newscrawler.core.newsletter_generator import NewsletterGenerator
    from newscrawler.core.utils.hf_cache import resolve_model
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_articles_data_source import (
        SQLAlchemyArticleDataSource,
    )
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
        SQLAlchemyNewsletterDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    client = client or SQLAlchemyClient()
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL_HF}")
    embeddings = HuggingFaceEmbeddings(
        model_name=resolve_model(EMBEDDING_MODEL_HF),          # OPS-32: the local cache first
        encode_kwargs={"batch_size": 64, "normalize_embeddings": True},
    )
    search = load_l1_search(embeddings) if with_l1 else None
    newsletter_ds = SQLAlchemyNewsletterDataSource(client)
    generator = NewsletterGenerator(newsletter_ds, embed_documents=embeddings.embed_documents,
                                    usage=SQLAlchemyKnowledgeDataSource(client), search_l1=search)
    return NewsletterService(NewsletterRepo(generator, SQLAlchemyArticleDataSource(client)))


__all__ = ["build_newsletter_service", "run_logged", "NewsletterService", "NewsletterRepo", "load_l1_search"]
