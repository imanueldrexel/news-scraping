from datetime import date

from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.antara_news.antaranews_branch import (
    AntaraNewsNetwork,
)
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from typing import List, Tuple, Dict, Union
import re
import logging

from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AntaraNewsCrawler(Crawler):
    def __init__(self):
        super(AntaraNewsCrawler, self).__init__()
        self.website_name = WebsiteName.ANTARANEWS.value

    def get_news_in_bulk(
        self, web_url: str, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        branches_to_crawl = AntaraNewsNetwork().get_all_url()
        links_to_crawl = []
        for branch_name, branch_link in branches_to_crawl.items():
            if isinstance(branch_link, str):
                logger.info(f"Scrape {branch_name} on {self.website_name}")
                soup = self.page_loader.get_soup(branch_link)
                if soup:
                    last_crawling, links = self._scrape(
                        soup,
                        last_crawling_time=last_crawling_time,
                    )
                    if links:
                        links_to_crawl.extend(links)
                    for branch_name_details, last_update in last_crawling.items():
                        if last_update:
                            last_crawling_time[branch_name_details] = last_update
        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_name}")
        return last_crawling_time, links_to_crawl

    def _scrape(self, soup, last_crawling_time) -> Tuple[Dict[str, date], List]:
        branch_name = self._get_branch_name(soup)
        articles = []
        latest_news_time = {k: [] for k, v in last_crawling_time.items()}
        for idx, url in enumerate(soup.find_all("item")):
            link = self._get_link(url)
            title = self._get_title(url, news_title_element_name="title")
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
    def _get_branch_name(sitemap_soup):
        sitemap_title_soup = sitemap_soup.find("title")
        if sitemap_title_soup:
            sitemap_title_soup = sitemap_title_soup.get_text(" ").split("-")[1:]
            branch_name = "".join(sitemap_title_soup).strip()
            return branch_name

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
            timestamp_string = timestamp_string.replace(" +0700", "")
            timestamp_string = re.sub(
                r"(.*)(, )([0-9]{2})(.*)", r"\3\4", timestamp_string
            )
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

    @staticmethod
    def _get_whole_text(soup) -> Union[None, List[str]]:
        def _remove_trailing_space(text) -> str:
            text = text.replace("\n", " ")
            text = text.replace("\r", " ")
            text = text.replace("\t", " ")
            text = re.sub(r"(\s+)", r" ", text)
            return text.strip()

        layer = soup.find("div", attrs={"class": ["post-content clearfix"]})
        if layer:
            while layer.br:
                layer.br.decompose()
            while layer.script:
                layer.script.decompose()
            while layer.span:
                layer.span.decompose()
            editor = soup.find("p", {"class": ["text-muted small mt10"]})
            if editor:
                layer.p.decompose()
            quote = soup.find("div", {"class": ["quote_old"]})
            if quote:
                layer.div.decompose()
            texts = []
            for sentence in _remove_trailing_space(layer.get_text(" ")).split("."):
                sentence = preprocess_text(sentence.strip())
                if sentence:
                    texts.append(sentence)
            return texts
