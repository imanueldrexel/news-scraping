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
        # SRC-05 (#16): the live index moved from <section>/sitemap_news.xml
        # (28 entries) to <section>/sitemap.xml; the old "sitemap_news" in link
        # filter matched nothing, so every run parsed 0 branches. Keep bisnis
        # (finance-relevant) -- see DBT-04 for widening to the other 27.
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if not link:
                continue
            link = link.get_text(" ").strip()
            match = re.match(r"https://www\.liputan6\.com/(\w+)/sitemap\.xml$", link)
            if match and match.group(1) == "bisnis":
                branches[match.group(1)] = link
        return branches

    @staticmethod
    def _get_link(news_soup) -> str:
        # SRC-05 (#16): unlike most other outlets, liputan6.com's article
        # pages 404 with ?page=all appended -- the base Crawler._get_link
        # appends it to every URL except JPNN, which broke every article
        # fetch here once _get_branches started finding real links again.
        link = news_soup.find("loc")
        if link:
            return link.get_text(" ").strip()

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
        # SRC-25 (#105): this was a bare `pass` (implicit None) -- crashed
        # _fetch_news_details' reporter filter (caught by SYS-02's guard, no
        # article lost, but a WARNING on every single one). No reliable byline
        # selector found in the static HTML (likely client-rendered); return
        # [] explicitly rather than reintroduce the same bug.
        return []
