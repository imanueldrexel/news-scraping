import logging
import re
from datetime import date
from typing import List, Tuple, Dict

from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BisnisCrawler(Crawler):
    def __init__(self):
        super(BisnisCrawler, self).__init__()
        self.website_name = WebsiteName.BISNIS.value

    def get_news_in_bulk(
        self, web_url: str, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        soup = self.page_loader.get_soup(web_url)

        counter = 0
        while not soup.find("div", {"class": "pretty-print"}) and counter < 5:
            soup = self.page_loader.get_soup(web_url)
            counter += 1
        links_to_crawl = []
        last_crawling, links = self._scrape(
            soup=soup, last_crawling_time=last_crawling_time
        )
        if links:
            links_to_crawl.extend(links)
        for branch_name_details, last_update in last_crawling.items():
            if last_update:
                last_crawling_time[branch_name_details] = last_update

        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_name}")
        return last_crawling_time, links_to_crawl

    def _scrape(self, soup, last_crawling_time) -> Tuple[Dict[str, date], List]:
        articles = []
        latest_news_time = {k: [] for k, v in last_crawling_time.items()}
        for idx, url in enumerate(soup.find_all("url")):
            link = self._get_link(url)
            branch_name = self._get_branch_name(link)

            title = self._get_title(url)
            keywords = self._get_keywords(url)
            last_stamped_crawling = last_crawling_time.get(branch_name)
            if not last_stamped_crawling:
                last_stamped_crawling = self.default_time
            timestamp_string, timestamp_datetime = self._get_timestamp(
                url, date_time_reader=self.date_time_reader
            )

            try:
                latest_news_time[branch_name].append(timestamp_datetime)
            except KeyError:
                latest_news_time[branch_name] = [timestamp_datetime]

            if timestamp_datetime > last_stamped_crawling:
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    "category": branch_name,
                    "sources": self.website_name,
                }
                articles.append(attributes)

        latest_news_time = {
            k: max(v) if len(v) > 0 else None for k, v in latest_news_time.items()
        }
        return latest_news_time, articles

    @staticmethod
    def _get_branch_name(url) -> str:
        branch_name = re.sub(r"(.*)(//)(.*)(.bisnis.com)(.*)", r"\3", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_link(news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            return link

    @staticmethod
    def _get_title(news_soup) -> str:
        title = news_soup.find("news:title")
        if title:
            title = title.get_text(" ").strip()
            return title

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader) -> Tuple[str, date]:
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_string = timestamp_string.replace("+07:00", "")
            timestamp_string = re.sub(
                r"(.*)(, )([0-9]{2})(.*)", r"\3\4", timestamp_string
            )
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find(
            "div",
            attrs={"itemprop": ["articleBody"], "class": ["col-sm-10", "copas", None]},
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
                    "Penulis:",
                    "Penulis :",
                    "Reporter:",
                    "Simak berita lainnya seputar",
                    "Bergabung dan dapatkan analisis informasi",
                ]
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in sentence.get_text(" "):
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if not sentence.find("div"):
                    tmp_text = preprocess_text(sentence.get_text(" ").strip())
                    if tmp_text:
                        texts.append(tmp_text)
            return texts
