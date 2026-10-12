"""QA 2026-10-12 (second pass), SYS-139: a factory a real SourceWorker child can import by name.

The child runs the real CrawlerServiceImpl batch loop behind the real CrawlerAPI. Only the crawler,
the store and the filter are fakes. Every batch sleeps QA_BATCH_S seconds. The deferred block (the
one FAISS flush of a source run, DBT-10) appends "flushed" to QA_FLUSH_MARKER when it is left
without an exception. A run killed by the worker's timeout never writes it.
"""
import contextlib
import os
import time
from unittest.mock import MagicMock, patch


class _Repo(MagicMock):
    @contextlib.contextmanager
    def deferred_embeddings(self, website=None):
        yield self
        with open(os.environ["QA_FLUSH_MARKER"], "a") as fh:
            fh.write("flushed\n")


def soft_deadline_factory():
    from newscrawler.application.api.crawler_api import CrawlerAPI
    from newscrawler.core.importance_filter import FilterDecision
    from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl

    batch_s = float(os.environ["QA_BATCH_S"])
    rows = [SitemapDTO(headline=f"h{i}", link=f"http://x/{i}", sources="VIVA", category="news", sitemap_id=i)
            for i in range(1, 101)]

    def crawl(news, website_name, throttle):
        time.sleep(batch_s)
        return [NewsDetailsDTO(sitemap_id=s.sitemap_id, extracted_text=["Bank Indonesia menahan suku bunga."],
                               reporter=None, meta_data={"title": s.headline}) for s in news]

    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=_Repo())
    crawler = MagicMock()
    crawler.batch_crawling_details.side_effect = crawl
    svc.crawler_dict = {"VIVA": crawler}
    svc.chunker = MagicMock()
    svc.chunker.chunk.return_value = ["chunk"]
    repo = svc.data_flow_repo
    repo.load_sitemap_data.return_value = rows
    repo.save_chunk_data.side_effect = lambda chunks: [r.sitemap_id for r in rows]
    repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    repo.get_last_fetch_errors.return_value = {}
    repo.discard_terminal_embeddings.return_value = 0
    svc.semantic_filter.classify.return_value = FilterDecision(True, "score", True)
    return CrawlerAPI(svc)
