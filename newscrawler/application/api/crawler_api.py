import logging
from typing import List

from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.services.crawler_service import CrawlerService

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CrawlerAPI:
    def __init__(self, crawler_service: CrawlerService):
        self.crawler_service = crawler_service

    def crawl_website(self, website_name: str, task: str):
        if task == "sitemap":
            self.crawler_service.crawl_sitemaps(website_name=website_name)
        elif task == "full_text":
            self.crawler_service.crawl_newsdetails(website_name=website_name)
        elif task == "all":
            sitemaps_dtos = self.crawler_service.crawl_sitemaps(website_name=website_name)
            # Load sitemaps from DB (not from in-memory) to ensure sitemap_id is populated
            self.crawler_service.crawl_newsdetails(website_name=website_name, specific_sitemaps=sitemaps_dtos)
        elif task == "extract_knowledge":
            # website-agnostic: processes all pending articles across all sources
            self.crawler_service.extract_knowledge()
        elif task == "newsletter":
            # website-agnostic: generates today's digest
            self.crawler_service.generate_newsletter()

    def crawl_websites_in_batch(self, website_names: List[str], task: str):
        if task in ("extract_knowledge", "newsletter"):
            logger.info(f"Running task '{task}' (website-agnostic)...")
            self.crawl_website(website_name="", task=task)
            return

        # One source must not take the rest of the run down with it (SYS-12). The
        # service layer already records each failure in crawl_log and re-raises; here
        # we isolate per source, keep going, and surface a single error at the end.
        succeeded, failed = [], {}
        for website_name in website_names:
            logger.info(f"Start scraping data for {website_name}...")
            try:
                self.crawl_website(website_name=website_name, task=task)
                succeeded.append(website_name)
            except Exception as e:
                failed[website_name] = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
                logger.error(f"{website_name} failed ({task}): {failed[website_name]}", exc_info=True)

        logger.info(
            f"Batch '{task}' finished: ok={len(succeeded)} failed={len(failed)}"
            + (f" | failed: {', '.join(f'{w} ({m})' for w, m in failed.items())}" if failed else "")
        )
        if failed:
            raise RuntimeError(
                f"{len(failed)} of {len(website_names)} sources failed: {', '.join(failed)}"
            )
