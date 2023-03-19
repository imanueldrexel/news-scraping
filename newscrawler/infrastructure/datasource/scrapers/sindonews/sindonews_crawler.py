import re

from datetime import date
from typing import List, Tuple, Dict

from bs4.element import NavigableString

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


class SindonewsCrawler(Crawler):
    def __init__(self):
        super(SindonewsCrawler, self).__init__()
        self.website_name = WebsiteName.SINDONEWS.value
        self.website_url = URL.SINDONEWS.value

    def get_news_in_bulk(
            self, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        soup = self.page_loader.get_soup(self.website_url)
        branches_to_crawl = self._get_branches(soup)
        links_to_crawl = []

        # up to branch -4, because there's no text in the categories afterwards
        for branch_name, branch_link in list(branches_to_crawl.items())[:-4]:
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
            link = sitemap.find("loc")
            if link and "sitemap-" not in link.get_text(" "):
                link = link.get_text(" ").strip()
                link = link.replace("sitemap.xml","sitemap-news.xml")
                branch_name = re.sub(r"(.*)(//)(.*)(.sindonews)(.*)", r"\3", link)
                branch_name = branch_name.strip()
                branches[branch_name] = link

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

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": ["content-show"]})
        full_text = []
        if multiple_pages:
            show_all = multiple_pages.find("a")
            if show_all:
                show_all = show_all["href"]
                soup = self.page_loader.get_soup(show_all)
                full_text = self._get_text(soup)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = None
        if layer is None:
            layer = soup.find(
                "div", attrs={"itemprop": ["articleBody"], "class": ["caption", None]}
            )
        if layer is None:
            layer = soup.find(
                "div",
                attrs={"class": ["article", "desc-artikel-detail", "detail-desc"], "itemprop": None},
            )
        if layer is None:
            layer = soup.find("section", attrs={"class": "article col-md-11"})

        layer_contents = sorted(layer.contents, key=lambda x: len(x), reverse=True)[0]
        if not isinstance(layer_contents, NavigableString):
            layer = layer_contents
        texts = []
        text = ""
        for x in layer.contents:
            if type(x) == NavigableString:
                tmp_text = preprocess_text(x.strip())
                text += " " + tmp_text
            else:
                avoided_keyword = [
                    "Baca Juga",
                    "Baca juga",
                    "Lihat Juga",
                    "Lihat juga",
                    "Penulis:",
                    "Penulis :",
                    "Reporter:",
                    "Simak berita lainnya seputar",
                    "Bergabung dan dapatkan analisis informasi",
                ]
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in x.get_text(" "):
                        continue_sentence = 1
                if continue_sentence:
                    continue
                else:
                    tmp_text = preprocess_text(x.get_text(" ").strip())
                    text += " " + tmp_text

        for sentence in text.split(". "):
            sentence = sentence.strip()
            if sentence:
                texts.append(sentence)
        return texts
