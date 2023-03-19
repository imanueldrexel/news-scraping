import logging
import re
from datetime import date
from typing import List, Tuple, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KontanCrawler(Crawler):
    def __init__(self):
        super(KontanCrawler, self).__init__()
        self.website_name = WebsiteName.KONTAN.value
        self.website_url = URL.KONTAN.value

    def get_news_in_bulk(
            self, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        soup = self.page_loader.get_soup(self.website_url)
        branches_to_crawl = self._get_branches(soup)
        links_to_crawl = []

        for branch_name, branch_link in branches_to_crawl.items():
            last_stamped_crawling = last_crawling_time.get(
                branch_name, self.default_time
            )
            last_crawling, links = self._scrape(
                branch_link=branch_link,
                branch_name=branch_name,
                last_stamped_crawling=last_stamped_crawling,
            )
            links_to_crawl.extend(links)
            last_crawling_time[branch_name] = last_crawling
        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_url}")
        return last_crawling_time, links_to_crawl

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            avoided_keyword = [
                "insight",
                "edsus",
                "exportexpert",
                "kilaskementerian",
                "kilaskorporasi",
                "pialaeropa",
            ]
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in link:
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if "/news/" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.kontan)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(
                            r"(https://www.kontan.co.id/)(.*)(/news/sitemap.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    def _scrape(
            self, branch_link, branch_name, last_stamped_crawling=None
    ) -> Tuple[date, List]:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return last_stamped_crawling, articles
        else:
            latest_news_delta = 999999999
            latest_news_time = None
            for idx, url in enumerate(soup.find_all("url")):
                link = self._get_link(url)
                title = self._get_title(url)
                keywords = self._get_keywords(url)
                timestamp_string, timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                (
                    time_posted,
                    delta,
                    delta_in_seconds,
                ) = self._get_delta_and_delta_in_second(
                    timestamp_string, last_stamped_crawling, self.date_time_reader
                )
                if delta_in_seconds < latest_news_delta:
                    latest_news_delta = delta_in_seconds
                if idx == 0:
                    latest_news_time = time_posted
                if delta.days >= 0 and delta.seconds > 0:
                    attributes = {
                        "link": link,
                        "headline": title,
                        "keywords": keywords,
                        "timestamp": timestamp_datetime,
                        "category": branch_name,
                        "sources": self.website_name,
                    }
                    articles.append(attributes)

            return latest_news_time, articles

    @staticmethod
    def _get_whole_text(soup):
        layer = soup.find(
            "div",
            attrs={
                "itemprop": ["articleBody"],
                "class": ["tmpt-desk-kon", "ctn", None],
            },
        )
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                avoided_keyword = [
                    "Baca Juga",
                    "Baca juga",
                    "Lihat Juga",
                    "Lihat juga",
                    "Selanjutnya",
                    "Penulis:",
                    "Penulis :",
                    "Reporter:",
                ]
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in sentence.get_text(" "):
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if not sentence.find("div"):
                    sentence = preprocess_text(sentence.get_text(" ").strip())
                    if sentence:
                        texts.append(sentence)
            return texts
