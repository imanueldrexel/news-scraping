import logging
import re
from datetime import date
from typing import List, Tuple, Dict

from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.core.utils.utils import preprocess_text

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class JPNNCrawler(Crawler):
    def __init__(self):
        super(JPNNCrawler, self).__init__()
        self.website_name = WebsiteName.JPNN.value

    def get_news_in_bulk(
        self, web_url: str, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        branch_name = "news"
        branch_link = web_url
        links_to_crawl = []

        last_stamped_crawling = last_crawling_time.get(branch_name)
        if not last_stamped_crawling:
            last_stamped_crawling = self.default_time

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
        self,
        branch_link: str,
        branch_name: str,
        last_stamped_crawling=None,
    ) -> Tuple[Dict[str, date], List]:
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return last_stamped_crawling, articles
        latest_news_delta = 999999999
        latest_news_time = None
        for idx, url in enumerate(soup.find_all("url")):
            link = self._get_link(url)
            title = self._get_title(url)
            keywords = self._get_keywords(url)
            timestamp_string, timestamp_datetime = self._get_timestamp(
                url, date_time_reader=self.date_time_reader
            )
            time_posted, delta, delta_in_seconds = self._get_delta_and_delta_in_second(
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
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

    @staticmethod
    def _get_delta_and_delta_in_second(
        timestamp, last_crawling, date_time_reader: DateTimeReader
    ):
        time_posted = timestamp.replace("T", " ").replace("+07:00", "")
        time_posted = date_time_reader.convert_date(time_posted)
        delta = time_posted - last_crawling
        delta_in_seconds = delta.days * 86400 + delta.seconds
        return time_posted, delta, delta_in_seconds

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": ["pagination"]})
        full_text = []

        if multiple_pages:
            list_soup = [soup]
            next_page = multiple_pages.find("a", {"class": "page larger"})
            if next_page:
                next_page = next_page["href"]
                next_page_soup = self.page_loader.get_soup(next_page)
                list_soup.append(next_page_soup)
            for s in list_soup:
                text = self._get_text(s)
                full_text.extend(text)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = soup.find("div", attrs={"itemprop": "articleBody"})
        if layer:
            sentences = layer.find_all("p")
            text = ""
            for sentence in sentences:
                while sentence.find_all("iframe"):
                    sentence.iframe.decompose()
                while sentence.find_all("div"):
                    sentence.div.decompose()
                while sentence.find_all("strong"):
                    sentence.strong.decompose()
                while sentence.find_all("br"):
                    sentence.br.decompose()
                tmp_text = preprocess_text(sentence.get_text(" ").strip())
                tmp_text = re.sub(r"(\s+)(\1+)", r"\1", tmp_text)
                if tmp_text not in text:
                    text += tmp_text.strip()
            return [t.strip() for t in text.split(". ")]
