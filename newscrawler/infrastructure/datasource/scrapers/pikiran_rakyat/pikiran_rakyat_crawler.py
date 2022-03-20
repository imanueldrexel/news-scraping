import os
import re
import logging
from datetime import date
from typing import List, Tuple, Dict


from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.core.utils.utils import (
    get_last_crawling_time,
    preprocess_text,
    set_last_crawling_time,
)
from newscrawler.infrastructure.datasource.scrapers.pikiran_rakyat.pikiran_rakyat_branch import (
    PikiranRakyatNetwork,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class PikiranRakyatCrawler(Crawler):
    def __init__(self):
        super(PikiranRakyatCrawler, self).__init__()
        self.date_time_reader = DateTimeReader()
        self.page_loader = RequestsPageLoader()
        self.website_name = WebsiteName.PIKIRANRAKYAT.value
        self.main_path = os.path.dirname(os.path.realpath(__file__))
        self.last_crawling_time = get_last_crawling_time(
            dir_path=self.main_path, website_name=self.website_name
        )

    def get_news_data(self, web_url: str) -> NewsInformationDTO:
        news = self.get_news_in_bulk(web_url)
        news_data = self.batch_crawling(news)

        set_last_crawling_time(
            last_crawling_time=self.last_crawling_time,
            dir_path=self.main_path,
            website_name=self.website_name,
        )
        return NewsInformationDTO(scraped_news=news_data)

    def get_news_in_bulk(self, web_url: str) -> List[Dict[str, any]]:
        branches_to_crawl = PikiranRakyatNetwork().get_all_url()

        links_to_crawl = []
        for branch_name, branch_link in branches_to_crawl.items():
            if isinstance(branch_link, str):
                logger.info(f"Scrape {branch_name} on {self.website_name}")
                soup = self.page_loader.get_soup(branch_link)
                if soup:
                    last_crawling, links = self._scrape(soup)
                    if links:
                        links_to_crawl.extend(links)
                    for branch_name_details, last_update in last_crawling.items():
                        if last_update:
                            self.last_crawling_time[branch_name_details] = last_update

        logger.info(
            f"Get {len(links_to_crawl)} to crawl in {self.website_name} crawler"
        )
        return links_to_crawl

    def _scrape(self, soup) -> Tuple[Dict[str, date], List]:

        articles = []
        latest_news_time = {k: [] for k, v in self.last_crawling_time.items()}
        for idx, url in enumerate(soup.find_all("url")):
            link = self._get_link(url)
            branch_name = self._get_branch_name(link)
            title = self._get_title(url)
            keywords = self._get_keywords(url)
            last_stamped_crawling = self.last_crawling_time.get(branch_name)
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
    def _get_branch_name(text):
        branch_name = re.sub(
            r"(https://)(.*)(.pikiran-rakyat.com)(.*)(/pr.*)(.*)", r"\2\4", text
        )
        return branch_name

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
            timestamp_string = timestamp_string.replace("+07:00", "")
            timestamp_string = re.sub(
                r"(.*)(, )([0-9]{2})(.*)", r"\3\4", timestamp_string
            )
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": ["paging__wrap clearfix"]})
        full_text = []
        if multiple_pages:
            pages = list(sorted(set([x["href"] for x in multiple_pages.find_all("a")])))
            for page in pages:
                if page != "#":
                    soup = self.page_loader.get_soup(page)
                texts = self._get_text(soup)
                if texts:
                    full_text.extend(texts)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = soup.find("div", attrs={"class": ["col-bs12-9"]})
        if layer:
            sentences = layer.find_all("p")
            if not sentences:
                sentences = layer.find_all("div")
            texts = []
            for sentence in sentences:
                avoided_keyword = [
                    "Baca Juga",
                    "Baca juga",
                    "Lihat Juga",
                    "Lihat juga",
                    "Penulis:",
                    "Penulis :",
                    "Editor:",
                    "Sumber: ",
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
                else:
                    extracted_text = preprocess_text(sentence.get_text(" ").strip())
                    if len(extracted_text) > 0:
                        texts.append(extracted_text)

            return texts
