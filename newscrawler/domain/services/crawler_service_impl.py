import logging
import math
from typing import List, Optional
from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.crawler_url_list import WEB_URL_DICT
from newscrawler.core.constants import INTERESTS
from newscrawler.core.importance_filter import SemanticImportanceFilter
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.domain.services.crawler_service import CrawlerService

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class CrawlerServiceImpl(CrawlerService):
    def __init__(
        self,
        data_flow_repo: DataFlowRepository,
        chunker: Optional[HierarchicalChunker] = None,
        limit: int = 1000,
    ):
        self.crawler_dict = CRAWLER_DICT
        self.web_url_dict = WEB_URL_DICT
        self.data_flow_repo = data_flow_repo
        self.newsdetails_limit = limit
        self.chunker = chunker or HierarchicalChunker()

        logger.info("Initializing Semantic Filter...")
        self.semantic_filter = SemanticImportanceFilter(
            interests=INTERESTS,
            model_name='paraphrase-multilingual-MiniLM-L12-v2'
        )

    def crawl_sitemaps(self, website_name: str) -> List[SitemapDTO]:
        log_id = self.data_flow_repo.log_crawl_start(website_name, "sitemap")
        try:
            web_crawler: Crawler = self.crawler_dict.get(website_name)
            raw_sitemaps  = web_crawler.get_news_in_bulk()
            sitemaps_dtos = web_crawler.batch_crawling_sitemap(raw_sitemaps, website_name)

            # SYS-07: log the number of newly-inserted rows, not "entries listed" --
            # a healthy source re-lists most of its sitemap on every run, so the old
            # len(sitemaps_dtos) told you nothing about whether new articles showed up.
            new_count = 0
            if sitemaps_dtos:
                sitemaps_dtos = self.save_scraped_data(sitemaps_dtos)
                new_count = getattr(sitemaps_dtos, "new_count", len(sitemaps_dtos))
                logger.info(f"Saved {len(sitemaps_dtos)} sitemaps. IDs populated.")

            self.data_flow_repo.log_crawl_complete(log_id, new_count)
            return sitemaps_dtos
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e))
            raise

    def crawl_newsdetails(self, website_name: str, specific_sitemaps: List[SitemapDTO] = None):
        log_id = self.data_flow_repo.log_crawl_start(website_name, "full_text")
        try:
            total_saved = self._crawl_newsdetails_inner(website_name, specific_sitemaps)
            self.data_flow_repo.log_crawl_complete(log_id, total_saved)
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e))
            raise

    def _crawl_newsdetails_inner(self, website_name: str, specific_sitemaps: List[SitemapDTO] = None) -> int:
        web_crawler: Crawler = self.crawler_dict.get(website_name)
        if specific_sitemaps:
            target_news = specific_sitemaps
        else:
            target_news = self.data_flow_repo.load_sitemap_data(website=website_name, n_limit=self.newsdetails_limit)

        logger.info(f"Found {len(target_news)} news to crawl for {website_name}")

        # Calculate batch size so that we have at most 10 batches
        batch_size = max(1, math.ceil(len(target_news) / 10))

        # SYS-04: track the funnel so crawl_log.article_count reflects reality and
        # the extracted/attempted ratio is visible per source -- the single most
        # useful "is this scraper rotting" signal.
        attempted = len(target_news)
        extracted_total = 0
        passed_filter_total = 0
        saved_total = 0

        for i in range(0, min(len(target_news), batch_size * 10), batch_size):
            logger.info(f"Processing batch {i//batch_size+1} for {website_name}")
            batch = target_news[i:i+batch_size]
            # Extract Articles from the batch
            newsdetails: List[NewsDetailsDTO] = web_crawler.batch_crawling_details(news=batch, website_name=website_name)
            
            if not newsdetails:
                continue

            extracted_total += len(newsdetails)
            logger.info(f"                  Batch {i//batch_size+1} has {len(newsdetails)} articles extracted.")

            # Bug B fix: mark every successfully-extracted sitemap as attempted so it is
            # not re-crawled until the cooldown elapses. Extraction failures are not in
            # `newsdetails`, so they remain eligible for retry on the next run.
            self.data_flow_repo.mark_sitemaps_attempted([n.sitemap_id for n in newsdetails])
            
            # --- Semantic Filtering ---
            important_newsdetails = []
            # SYS-16: a rejection is either permanent (real text, but off-topic --
            # the same headline/body will fail the same INTERESTS check every time)
            # or transient (no extractor produced usable text this run -- a layout
            # fix or a later attempt could still succeed). Only the former should
            # stop being re-queued; the latter keeps the normal cooldown retry.
            rejected_filter_ids = []
            empty_extraction_ids = []
            for news in newsdetails:
                try:
                    # Construct text for checking (Title + Content Snippet)
                    title = news.meta_data.get('title', '')
                    # Clean/prepare text snippet
                    full_text = " ".join(news.extracted_text) if isinstance(news.extracted_text, list) else str(news.extracted_text)
                    check_text = f"{title} {full_text[:500]}"

                    if self.semantic_filter.is_important(check_text):
                        important_newsdetails.append(news)
                    elif full_text.strip():
                        rejected_filter_ids.append(news.sitemap_id)
                    else:
                        empty_extraction_ids.append(news.sitemap_id)
                except Exception as e:
                    logger.warning(f"Error filtering news {news.sitemap_id}: {e}")

            passed_filter_total += len(important_newsdetails)
            logger.info(f"                  Filtered: {len(newsdetails) - len(important_newsdetails)} unimportant articles.")
            logger.info(f"                  Remaining: {len(important_newsdetails)} important articles.")

            if rejected_filter_ids:
                self.data_flow_repo.mark_sitemaps_status(rejected_filter_ids, "rejected_filter")
            if empty_extraction_ids:
                self.data_flow_repo.mark_sitemaps_status(empty_extraction_ids, "empty_extraction")

            if important_newsdetails:
                try:
                    # Build sitemap lookup so chunker gets source/category metadata
                    sitemap_by_id = {s.sitemap_id: s for s in batch}

                    all_chunks = []
                    for news in important_newsdetails:
                        sitemap_meta = sitemap_by_id.get(news.sitemap_id)
                        all_chunks.extend(self.chunker.chunk(news, sitemap_meta))

                    embedded_sitemap_ids = self.data_flow_repo.save_chunk_data(all_chunks)

                    if embedded_sitemap_ids:
                        logger.info(f"Embedded {len(embedded_sitemap_ids)} articles as chunks, batch {i//batch_size+1}")
                        to_save = [n for n in important_newsdetails if n.sitemap_id in set(embedded_sitemap_ids)]
                        # SYS-04: drive both the count and the 'saved' stamp from what
                        # actually committed, not from what was handed to persistence
                        # -- save_newsdetails_data can commit fewer rows than to_save
                        # (a per-row savepoint failure, or on_conflict_do_nothing for
                        # a sitemap that already has an article).
                        committed_sitemap_ids = list(self.save_scraped_data(to_save) or [])
                        if committed_sitemap_ids:
                            self.data_flow_repo.mark_sitemaps_status(committed_sitemap_ids, "saved")
                        saved_total += len(committed_sitemap_ids)
                        logger.info(
                            f"Saved batch {i//batch_size+1} for {website_name}: "
                            f"{len(committed_sitemap_ids)}/{len(to_save)} rows actually committed"
                        )
                except Exception as e:
                    logger.error(f"Error saving batch {i//batch_size+1} for {website_name}: {e}")
                    continue

        logger.info(
            f"Full-text crawl finished for {website_name}: "
            f"attempted={attempted} extracted={extracted_total} "
            f"passed_filter={passed_filter_total} saved={saved_total}"
        )
        return saved_total

    def extract_knowledge(self) -> int:
        logger.info("Starting knowledge extraction phase...")
        count = self.data_flow_repo.extract_knowledge()
        logger.info(f"Knowledge extraction complete. Processed {count} articles.")
        return count

    def generate_newsletter(self, target_date=None):
        logger.info(f"Starting newsletter generation for {target_date or 'today'}...")
        path = self.data_flow_repo.generate_newsletter(target_date)
        logger.info(f"Newsletter generated: {path}")
        return path

    def save_scraped_data(self, scraped_data):
        if not scraped_data:
            return []
        if isinstance(scraped_data[0], SitemapDTO):
            return self.data_flow_repo.save_sitemap_data(scraped_data)  # add return
        elif isinstance(scraped_data[0], NewsDetailsDTO):
            # SYS-04: return what was actually committed (a list of sitemap_ids),
            # not the input DTOs -- callers need to know what landed, not what was
            # attempted.
            return self.data_flow_repo.save_newsdetails_data(scraped_data)

