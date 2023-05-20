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


class MerdekaCrawler(Crawler):
    def __init__(self):
        super(MerdekaCrawler, self).__init__()
        self.website_name = WebsiteName.MERDEKA.value
        self.website_url = URL.MERDEKA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.MERDEKA.value}
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        paragraphs = soup.find_all("div", attrs={"class": "mdk-body-paragraph"})
        texts = []
        for paragraph in paragraphs:
            sentences = paragraph.find_all("p")
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence:
                    if sentence in ['Advertisement']:
                        continue
                    texts.append(sentence)
        return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("span", {"class": ["reporter"]})
        if layer:
            reporter = layer.get_text(" ")
            if reporter:
                reporter = reporter.replace("Reporter : ", "")
                reporters.append(reporter.strip())
        return reporters

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://www.merdeka.com/)(\w+)(/.*)", r"\2", url)
        if branch_name:
            return branch_name.strip()
