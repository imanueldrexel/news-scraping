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

        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_name}")
        return last_crawling_time, links_to_crawl

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
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "/news/" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.bisnis)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(
                            r"(https://www.bisnis.com/)(.*)(/news/sitemap.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        print(branches)
        return branches

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
