import logging
from typing import List

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.services.crawler_service import CrawlerService

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-21: crawl_website dispatched on a free-form string with no exhaustive
# else/validation, so a typo'd CRAWL_TASK or a missing "task" key ran the whole
# website list, called no service method, wrote no crawl_log row, raised nothing,
# and exited 0 -- indistinguishable from a healthy run everywhere we look.
VALID_TASKS = ("sitemap", "full_text", "all", "extract_knowledge", "newsletter")
# These two ignore website_name entirely (process everything pending across all
# sources), so an empty/absent website list is expected for them, not an error.
WEBSITE_AGNOSTIC_TASKS = ("extract_knowledge", "newsletter")


class CrawlerAPI:
    def __init__(self, crawler_service: CrawlerService):
        self.crawler_service = crawler_service

    def crawl_website(self, website_name: str, task: str):
        if task == "sitemap":
            self.crawler_service.crawl_sitemaps(website_name=website_name)
        elif task == "full_text":
            self.crawler_service.crawl_newsdetails(website_name=website_name)
        elif task == "all":
            self.crawler_service.crawl_sitemaps(website_name=website_name)
            # SYS-07: don't hand crawl_sitemaps' own return value to crawl_newsdetails
            # as specific_sitemaps -- that list is every sitemap the site currently
            # lists (existing rows included, since save_sitemaps' dedup returns their
            # ids too), so it bypassed load_all_sitemaps' "no articles row yet AND
            # cooldown elapsed" filter entirely and re-fetched every URL a site lists
            # on every single run (no articles row -> duplicate row every time,
            # since articles has no per-sitemap uniqueness before DBT-07, and even
            # after it, wasted full-text fetches forever). Passing no specific_sitemaps
            # makes crawl_newsdetails load from the DB instead, which gives the
            # cooldown + no-article filter + 1,000-row limit for free.
            self.crawler_service.crawl_newsdetails(website_name=website_name)
        elif task == "extract_knowledge":
            # website-agnostic: processes all pending articles across all sources
            self.crawler_service.extract_knowledge()
        elif task == "newsletter":
            # website-agnostic: generates today's digest
            self.crawler_service.generate_newsletter()
        else:
            # Backstop: crawl_websites_in_batch already validates task up front, but
            # this method can be called directly too, and a silent no-op here is
            # exactly the SYS-21 bug -- fail loudly instead.
            raise ValueError(f"Unknown task {task!r}; must be one of {VALID_TASKS}")

    def crawl_websites_in_batch(self, website_names: List[str], task: str):
        if task not in VALID_TASKS:
            raise ValueError(f"Unknown task {task!r}; must be one of {VALID_TASKS}")

        if task not in WEBSITE_AGNOSTIC_TASKS:
            # SYS-30: the third silent input after SYS-21's two. lambda_handler maps
            # an absent "website" key to [] because the agnostic tasks need none, so
            # process_event({"task": "all"}) reached here with nothing to crawl,
            # called no service method, logged "ok=0 failed=0" and exited 0.
            if not website_names:
                raise ValueError(
                    f"task {task!r} needs at least one website "
                    f"(only {WEBSITE_AGNOSTIC_TASKS} run without one)"
                )
            # Validate every name before any work starts -- a batch that's already
            # crawled 3 sites shouldn't discover the 4th name was a typo only when
            # it crashes crawl_sitemaps with an AttributeError on None.
            unknown = [w for w in website_names if w not in CRAWLER_DICT]
            if unknown:
                raise ValueError(f"Unknown website name(s): {', '.join(unknown)}")

        if task in WEBSITE_AGNOSTIC_TASKS:
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
