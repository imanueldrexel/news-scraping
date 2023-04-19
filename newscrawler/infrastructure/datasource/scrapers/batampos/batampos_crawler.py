import logging
from typing import List, Dict

from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BatamposCrawler(Crawler):
    def __init__(self):
        super(BatamposCrawler, self).__init__()
        self.website_name = WebsiteName.BATAMPOS.value
        self.website_url = URL.BATAMPOS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.BATAMPOS.value}
        return branches

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords

    @staticmethod
    def _get_whole_text(soup):
        sentences = soup.find_all("p")
        texts = []
        for sentence in sentences:
            sentence = preprocess_text(sentence.get_text(" ").strip())
            if sentence:
                texts.append(sentence)
        return texts
