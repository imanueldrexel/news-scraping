import logging
from datetime import datetime
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.website_name import WebsiteName

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class EmitennewsCrawler(Crawler):
    def __init__(self):
        super(EmitennewsCrawler, self).__init__()
        self.website_name = WebsiteName.EMITENNEWS.value
        self.website_url = URL.EMITENNEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.EMITENNEWS.value}
        return branches

    def _scrape(
            self, branch_link, branch_name
    ) -> List:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return articles
        else:
            for idx, url in enumerate(soup.find_all("url")):
                link = self._get_link(url)
                if "/news/" not in link:
                    continue
                title = self._get_title(url, news_title_element_name="title")
                keywords = self._get_keywords(url)
                timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                new_branch_name = self._get_branch_name_from_url(link)
                branch_name = new_branch_name if new_branch_name != link else new_branch_name
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    "category": branch_name,
                    "sources": self.website_name,
                }
                articles.append(attributes)
            return articles

    @staticmethod
    def _get_link(news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            if "?page=all" not in link:
                link += "?page=all"
            return link

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            title = link.replace("https://www.emitennews.com/news/", "")
            title = title.replace("-", " ")
            title = title.title()
            return title

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        return datetime.now()

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"class": "read__content"})
        if not read_content_layer:
            read_content_layer = soup.find(
                "div", attrs={"class": "side-article txt-article"}
            )
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence and "Baca juga" not in sentence:
                    texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", attrs={"class": "read__credit__item"})
        for reporter in layers:
            reporter = reporter.find("a")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporter = reporter.strip()
                    reporters.append(reporter)

        return reporters
