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

    def get_news_in_bulk(
        self, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        headless_page_loader = HeadlessPageLoader()
        soup = headless_page_loader.get_soup(self.website_url)
        links_to_crawl = []
        last_crawling, links = self._scrape(soup, last_crawling_time=last_crawling_time)
        if links:
            links_to_crawl.extend(links)
        for branch_name_details, last_update in last_crawling.items():
            if last_update:
                last_crawling_time[branch_name_details] = last_update

        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_name}")
        return last_crawling_time, links_to_crawl

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

    @staticmethod
    def _get_branch_name(text):
        branch_name = re.sub(r"(.*)(//)(.*)(.liputan6)(.*)", r"\3", text)
        if branch_name == "www":
            branch_name = re.sub(
                r"(https://www.liputan6.com/)(.*)(/read)(.*)", r"\2", text
            )

        return branch_name
