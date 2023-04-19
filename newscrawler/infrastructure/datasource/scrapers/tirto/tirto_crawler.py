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


class TirtoCrawler(Crawler):
    def __init__(self):
        super(TirtoCrawler, self).__init__()
        self.website_name = WebsiteName.TIRTO.value
        self.website_url = URL.TIRTO.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.TIRTO.value}
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find_all("div", {"class": "content-text-editor"})
        if article_layer:
            texts = []
            for sentence in article_layer[1:]:
                while sentence.find_all("script"):
                    sentence.script.decompose()
                while sentence.find_all("div"):
                    sentence.div.decompose()
                sentence = preprocess_text(sentence.get_text(" ")).split(". ")
                texts.extend(sentence)
            return texts
