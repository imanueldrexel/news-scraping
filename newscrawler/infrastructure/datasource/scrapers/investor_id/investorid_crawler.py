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


class InvestorIDCrawler(Crawler):
    def __init__(self):
        super(InvestorIDCrawler, self).__init__()
        self.website_name = WebsiteName.INVESTORID.value
        self.website_url = URL.INVESTORID.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.INVESTORID.value}
        return branches

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://investor.id/)(\w+)(/)(.*)", r"\2", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find("div", {"class": ["body-content"]})
        if article_layer:
            while article_layer.find_all("div"):
                article_layer.div.decompose()
            while article_layer.find_all("script"):
                article_layer.script.decompose()
            sentences = article_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text())
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": ["col small pt-1"]})
        if layer:
            reporter = layer.find("b")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporters.append(reporter.strip())
        return reporters
