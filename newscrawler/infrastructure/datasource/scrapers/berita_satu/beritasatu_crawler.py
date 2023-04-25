import logging
import re
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BeritaSatuCrawler(Crawler):
    def __init__(self):
        super(BeritaSatuCrawler, self).__init__()
        self.website_name = WebsiteName.BERITASATU.value
        self.website_url = URL.BERITASATU.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "/news" in link:
                    branch_name = re.sub(
                        r"(https://www.beritasatu.com/sitemap/)(.*)(/news.xml)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        texts = []
        articles = soup.find_all("div", {"class": "row mt-3"})
        for article in articles:
            col = article.find("div", {"class": "col"})
            if col:
                sentences = col.find_all("p")
                for sentence in sentences:
                    sentence = preprocess_text(sentence.get_text(" ").strip())
                    texts.append(sentence)
        return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", {"class": "row mb-3"})
        for layer in layers:
            col = layer.find("div", {"class": "col"})
            col = col.find("b")
            col = col.get_text(" ").strip()
            if col:
                reporter = col.split("/")[0]
                reporter = reporter.split(",")
                reporter = [r.strip() for r in reporter]
                reporters.extend(reporter)

        return reporters
