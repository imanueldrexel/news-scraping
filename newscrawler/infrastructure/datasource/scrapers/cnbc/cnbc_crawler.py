import re
import logging
from typing import Dict, List

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CNBCCrawler(Crawler):
    def __init__(self):
        super(CNBCCrawler, self).__init__()
        self.website_name = WebsiteName.CNBC.value
        self.website_url = URL.CNBC.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap_news" in link:
                    branch_name = re.sub(
                        r"(https://www.cnbcindonesia.com/)(.*)(/)(.*)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup):
        layer = soup.find("div", {"class": "detail_text"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence:
                    texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": "author"})
        if layer:
            reporter = layer.get_text(" ")
            if reporter:
                reporter = reporter.split(",")
                if reporter:
                    reporter = reporter[0].split("-")
                    if reporter:
                        reporters.append(reporter[1].strip())
        return reporters
