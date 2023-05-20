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


class EraIDCrawler(Crawler):
    def __init__(self):
        super(EraIDCrawler, self).__init__()
        self.website_name = WebsiteName.ERAID.value
        self.website_url = URL.ERAID.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.ERAID.value}
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find("article")
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                texts.append(sentence)

            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("ul", {"class": ["author-lists"]})
        if layer:
            layers = layer.find_all("li")
            for reporter in layers:
                reporter = reporter.find("a")
                if reporter:
                    if not isinstance(reporter, int):
                        reporter = preprocess_text(reporter.get_text(" ").strip())
                        if reporter:
                            reporters.append(reporter)
                    else:
                        continue
        return list(set(reporters))

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://era.id/)(\w+)(/.*)", r"\2", url)
        if branch_name:
            return branch_name.strip()