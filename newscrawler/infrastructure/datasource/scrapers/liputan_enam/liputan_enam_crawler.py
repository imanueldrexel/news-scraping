import re
from datetime import date

from typing import List, Tuple, Dict

from newscrawler.core.page_loader.headless_page_loader import HeadlessPageLoader
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LiputanEnamCrawler(Crawler):
    def __init__(self):
        super(LiputanEnamCrawler, self).__init__()
        self.website_name = WebsiteName.LIPUTAN6.value
        self.website_url = URL.LIPUTAN6.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap_news" in link:
                    try:
                        branch_name = re.sub(r"(https://www.liputan6.com/)(.*)(/sitemap_news.xml)", r"\2", link)
                    except BaseException:
                        branch_name = "news"
                    branches[branch_name] = link.strip()
        return branches

    def _get_whole_text(self, soup):
        pages = soup.find_all(
            "div", attrs={"class": "article-content-body__item-content"}
        )
        full_text = []
        for page in pages:
            texts = self._get_text(page)
            if texts:
                full_text.extend(texts)
        return full_text

    @staticmethod
    def _get_text(soup):
        sentences = soup.find_all("p")
        texts = []
        for sentence in sentences:
            sentence_text = preprocess_text(sentence.get_text(" ").strip())
            if "Baca Juga" in sentence_text or sentence.find("em"):
                continue
            elif sentence_text:
                texts.append(sentence_text)
        return texts


    def _get_reporter_from_text(self, soup) -> List[str]:
        pass
