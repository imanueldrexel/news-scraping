from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.infrastructure.datasource.scrapers.grid_id.grid_id_branch import (
    GridIdNetwork,
)
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from typing import Dict, List
import re
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class GridIdCrawler(Crawler):
    def __init__(self):
        super(GridIdCrawler, self).__init__()
        self.website_name = WebsiteName.GRIDID.value
        self.website_url = URL.GRIDID.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = GridIdNetwork().get_all_url()
        return branches

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://)(\w+)(\..*)", r"\2", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_whole_text(soup):
        layer = soup.find("div", {"class": ["read__article"]})
        if layer:
            sentences = layer.find_all("p")
            if sentences:
                texts = []
                for sentence in sentences:
                    sentence_em = sentence.find("em")
                    if sentence_em:
                        continue
                    else:
                        sentence = preprocess_text(sentence.get_text(" "))
                        if sentence and "Baca Juga" not in sentence:
                            texts.append(sentence)
                return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("span", {"class": ["read__author"]})
        if layer:
            reporter = layer.get_text(" ")
            if reporter:
                reporters.append(reporter.strip())
        return reporters
