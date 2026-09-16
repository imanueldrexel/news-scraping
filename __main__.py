from dotenv import load_dotenv
load_dotenv()

import logging
import os

from newscrawler.application.api.lambda_function import lambda_handler

logger = logging.getLogger(__name__)

# Outlets that pass scripts/check_crawlers.py as of 2026-09-16. Override with
#   CRAWL_WEBSITES=KOMPAS,CNBC   (comma-separated)   CRAWL_TASK=sitemap|full_text|all
HEALTHY = [
    "BERITASATU", "CNBC", "CNN", "DETIK", "EMITENNEWS", "ERAID", "GRIDID", "IDXCHANNEL",
    "INVESTORID", "JPNN", "KOMPAS", "KONTAN", "KUMPARAN", "MEDIAINDONESIA", "OKEZONE",
    "PIKIRANRAKYAT", "SINDONEWS", "TRIBUN", "TVONENEWS", "VIVA", "WARTAEKONOMI",
]
# Broken -- re-add when the ticket closes (see AUDIT_2026-09-15.md):
#   ANTARANEWS, BATAMPOS, KAPANLAGI, TIRTO, SUARA   SRC-02  dead / wrong sitemap URL
#   BISNIS, IDNTIMES                                SRC-03  403 at the sitemap level
#   INEWS                                           SRC-04  TLS certificate failure
#   LIPUTAN6                                        SRC-05  sitemap index format changed
#   MERDEKA, TEMPO                                  SRC-06  branch sitemap format changed


def main():
    override = os.getenv("CRAWL_WEBSITES")
    websites = [w.strip().upper() for w in override.split(",") if w.strip()] if override else HEALTHY
    task = os.getenv("CRAWL_TASK", "all")
    logger.info(f"Crawling {len(websites)} websites, task={task}: {', '.join(websites)}")
    lambda_handler.process_event({"website": ",".join(websites), "task": task}, None)


if __name__ == "__main__":
    main()
