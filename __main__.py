from dotenv import load_dotenv
load_dotenv()

import logging
import os

from newscrawler.application.api.lambda_function import lambda_handler

logger = logging.getLogger(__name__)

# Outlets that pass scripts/check_crawlers.py as of 2026-09-19 (OK or FALLBACK
# -- a dead site-specific selector rescued by trafilatura still produces
# real articles, same bar the original 2026-09-16 list already used for
# CNBC/CNN/KONTAN/PIKIRANRAKYAT). Override with
#   CRAWL_WEBSITES=KOMPAS,CNBC   (comma-separated)   CRAWL_TASK=sitemap|full_text|all
HEALTHY = [
    "ANTARANEWS", "BERITASATU", "CNBC", "CNN", "DETIK", "EMITENNEWS", "ERAID", "GRIDID",
    "IDNTIMES", "IDXCHANNEL", "INEWS", "INVESTORID", "JPNN", "KOMPAS", "KONTAN", "KUMPARAN",
    "LIPUTAN6", "MEDIAINDONESIA", "MERDEKA", "OKEZONE", "PIKIRANRAKYAT", "SINDONEWS",
    "SUARA", "TEMPO", "TIRTO", "TRIBUN", "TVONENEWS", "VIVA", "WARTAEKONOMI",
]
# Broken -- re-add when the ticket closes:
#   BISNIS   SRC-03   genuine Cloudflare managed challenge, needs a headless
#            browser to even attempt (confirmed 2026-09-19, not pursued)
# KAPANLAGI and BATAMPOS were retired 2026-09-20 (SRC-17/SRC-18) -- no usable
# finance content -- and are no longer registered anywhere in the pipeline.


def main():
    override = os.getenv("CRAWL_WEBSITES")
    websites = [w.strip().upper() for w in override.split(",") if w.strip()] if override else HEALTHY
    task = os.getenv("CRAWL_TASK", "all")
    logger.info(f"Crawling {len(websites)} websites, task={task}: {', '.join(websites)}")
    lambda_handler.process_event({"website": ",".join(websites), "task": task}, None)


if __name__ == "__main__":
    main()
