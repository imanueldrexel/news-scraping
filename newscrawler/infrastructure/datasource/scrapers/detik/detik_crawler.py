import re
import logging
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


class DetikCrawler(Crawler):
    def __init__(self):
        super(DetikCrawler, self).__init__()
        self.website_name = WebsiteName.DETIK.value
        self.website_url = URL.DETIK.value

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
                        r"(https://)(.*)(.detik.com/)(.*)(/sitemap_news.xml)", r"\4", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find("div", attrs={"class": "detail__body"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence in ['ADVERTISEMENT', 'SCROLL TO RESUME CONTENT']:
                    continue
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": ["detail__author"]})
        if layer:
            reporter = layer.get_text(" ")
            if reporter:
                reporter = reporter.split("-")[0]
                reporters.append(reporter.strip())
        return reporters
