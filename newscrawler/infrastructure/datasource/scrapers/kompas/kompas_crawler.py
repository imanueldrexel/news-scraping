import logging
import os
import re
from datetime import date
from typing import List, Tuple, Dict

from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import get_last_crawling_time, set_last_crawling_time, \
    preprocess_text
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KompasCrawler(Crawler):
    def __init__(self):
        super(KompasCrawler, self).__init__()
        self.date_time_reader = DateTimeReader()
        self.website_name = WebsiteName.KOMPAS.value
        self.page_loader = RequestsPageLoader()
        self.main_path = os.path.dirname(os.path.realpath(__file__))

    def get_news_data(self, web_url: str) -> NewsInformationDTO:
        last_crawling_time, news = self.get_news_in_bulk(web_url)
        news_data = self.batch_crawling(news)
        set_last_crawling_time(last_crawling_time=last_crawling_time,
                               dir_path=self.main_path,
                               website_name=self.website_name)
        return NewsInformationDTO(scraped_news=news_data)

    def get_news_in_bulk(self, web_url) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        soup = self.page_loader.get_soup(web_url)
        branches_to_crawl = self._get_branches(soup)
        last_crawling_time = get_last_crawling_time(dir_path=self.main_path, website_name=self.website_name)
        links_to_crawl = []

        for branch_name, branch_link in branches_to_crawl.items():
            last_stamped_crawling = last_crawling_time.get(branch_name, self.default_time)
            last_crawling, links = self._scrape(branch_link=branch_link,
                                                branch_name=branch_name,
                                                last_stamped_crawling=last_stamped_crawling)
            links_to_crawl.extend(links)
            last_crawling_time[branch_name] = last_crawling

        logger.info(f'get {len(links_to_crawl)} to scrape for {self.website_name}')
        return last_crawling_time, links_to_crawl

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(' ').strip()
                if "/news/" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.kompas)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(r"(https://www.kompas.com/)(.*)(/news/sitemap.xml)", r"\2", link)
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    def _scrape(self, branch_link, branch_name, last_stamped_crawling=None) -> Tuple[date, List]:
        logger.info(f'Scrape {branch_name} on {self.website_name}')
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
                timestamp_string, timestamp_datetime = self._get_timestamp(url, date_time_reader=self.date_time_reader)
                time_posted, delta, delta_in_seconds = self._get_delta_and_delta_in_second(timestamp_string,
                                                                                           last_stamped_crawling,
                                                                                           self.date_time_reader)
                if delta_in_seconds < latest_news_delta:
                    latest_news_delta = delta_in_seconds
                if idx == 0:
                    latest_news_time = time_posted
                if delta.days >= 0 and delta.seconds > 0:
                    attributes = {
                        'link': link,
                        'headline': title,
                        'keywords': keywords,
                        'timestamp': timestamp_datetime,
                        'category': branch_name,
                        'sources': self.website_name
                    }
                    articles.append(attributes)

            return latest_news_time, articles

    @staticmethod
    def _get_link(news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(' ').strip()
            return link

    @staticmethod
    def _get_title(news_soup) -> str:
        title = news_soup.find("news:title")
        if title:
            title = title.get_text(' ').strip()
            return title

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(' ').strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(' ').strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

    @staticmethod
    def _get_delta_and_delta_in_second(timestamp, last_crawling, date_time_reader: DateTimeReader):
        time_posted = timestamp.replace("T", " ").replace("+07:00", "")
        time_posted = date_time_reader.convert_date(time_posted)
        delta = time_posted - last_crawling
        delta_in_seconds = delta.days * 86400 + delta.seconds
        return time_posted, delta, delta_in_seconds

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"class": "read__content"})
        if not read_content_layer:
            read_content_layer = soup.find('div', attrs={'class': 'side-article txt-article'})
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(' ').strip())
                if sentence and "Baca juga" not in sentence:
                    texts.append(sentence)
            return texts