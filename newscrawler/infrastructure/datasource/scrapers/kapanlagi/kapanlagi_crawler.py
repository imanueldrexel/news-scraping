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


class KapanlagiCrawler(Crawler):
    def __init__(self):
        super(KapanlagiCrawler, self).__init__()
        self.website_name = WebsiteName.KAPANLAGI.value
        self.website_url = URL.KAPANLAGI.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.KAPANLAGI.value}
        return branches

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://www.kapanlagi.com/)(\w+)(/)(.*)", r"\2", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        texts = []
        layer = soup.find(
            "div",
            attrs={"class": "body-paragraph clearfix mainpart trial-html"},
        )
        if layer:
            sentences = layer.find_all("p")
            for sentence in sentences:
                sentence_text = preprocess_text(sentence.get_text(" ").strip())
                sentence_caption = sentence.find(
                    "div", attrs={"class": ["entertainment-newsdetail-image-caption"]}
                )
                if sentence_caption or (not sentence_text) or (sentence_text in texts):
                    continue
                else:
                    sentence_text = re.sub(r"(\s+)(\1+)", r"\1", sentence_text)
                    if sentence_text:
                        texts.append(sentence_text)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        pass