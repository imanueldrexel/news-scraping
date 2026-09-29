from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.infrastructure.datasource.scrapers.antara_news.antaranews_branch import (
    AntaraNewsNetwork,
)
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from typing import List, Dict
import re
import logging


logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AntaraNewsCrawler(Crawler):
    # DBT-05 (#24): this source's site selector had been dead for months (trafilatura
    # produced every saved article); trafilatura is its extractor by design.
    PRIMARY_EXTRACTOR = "trafilatura"

    def __init__(self):
        super(AntaraNewsCrawler, self).__init__()
        self.website_name = WebsiteName.ANTARANEWS.value
        self.website_url = URL.ANTARANEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        # SRC-13 (#91): AntaraNewsNetwork.get_all_url() returns all ~60 feeds
        # (politik, hukum, metro, sepakbola*, olahraga*, lifestyle*, hiburan*,
        # tekno*, otomotif*, ...) -- 55 of them off-topic for a finance
        # pipeline (SYS-31). Restrict to the ekonomi* feeds; BUMNUntukNegeri is
        # dropped because it 404s.
        network = AntaraNewsNetwork()
        return {
            "Ekonomi": network.Ekonomi,
            "Finansial": network.Finansial,
            "Bisnis": network.Bisnis,
            "Bursa": network.Bursa,
        }

    def _scrape(self, branch_link, branch_name) -> List:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return articles
        else:
            for idx, url in enumerate(soup.find_all("item")):
                link = self._get_link(url)
                title = self._get_title(url, news_title_element_name="title")
                keywords = self._get_keywords(url)
                timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    # SRC-13 (#91): the old _get_branch_name_from_url override
                    # always returned the fixed string "ANTARA News" regardless
                    # of feed, so every row's category was identical no matter
                    # which of the 4 ekonomi* branches it came from. branch_name
                    # here is the dict key _get_branches assigned
                    # ("Ekonomi"/"Finansial"/"Bisnis"/"Bursa") -- use it as-is.
                    "category": branch_name,
                    "sources": self.website_name,
                }
                articles.append(attributes)
            return articles

    @staticmethod
    def _get_link(news_soup) -> str:
        link = news_soup.find("guid")
        if link:
            link = link.get_text(" ").strip()
            return link

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("pubdate")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_datetime

    def _get_reporter_from_text(self, soup) -> List[str]:
        # SRC-21 (#101): every path used to fall off the end and implicitly
        # return None when no byline paragraph was found (common on this wire
        # service) -- _fetch_news_details iterates this result right after
        # calling it, and iterating None raised a TypeError caught (and
        # correctly handled as reporter=[]) by SYS-02's crash guard, but only
        # after a noisy WARNING on every such article.
        try:
            layer = soup.find("div", attrs={"class": ["post-content clearfix"]})
            if layer:
                paragraph = soup.find("p", attrs={"class": ["text-muted small mt10"]})
                if paragraph:
                    paragraph = paragraph.get_text(" ").split("\t")
                    if paragraph:
                        paragraph = paragraph[0]
                        paragraph = paragraph.replace("Pewarta: ", "").replace(
                            "Editor: ", "\n"
                        )
                        paragraph = [x.strip() for x in paragraph.split("\n")]
                        return paragraph
        except BaseException as e:
            logger.info(f"Error while get reporter from text\nReason:{e}")
        return []
