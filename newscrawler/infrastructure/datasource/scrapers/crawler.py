import logging
import os
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Dict, Union, Any

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Crawler:
    def __init__(self):
        self.verbose = VERBOSE
        self.parallelize = PARALLELIZE
        self.date_time_reader = DateTimeReader()
        self.main_path = os.path.dirname(os.path.realpath(__file__))
        self.default_time = self.date_time_reader.convert_date("2000-01-01 00:00:01")
        self.max_worker = MAX_WORKER
        self.page_loader = RequestsPageLoader()
        self.website_url = None
        self.website_name = None

    def batch_crawling(self, news: List[Dict[str, str]], website_name: str) -> NewsInformationDTO:
        news_data = []
        if not news:
            return NewsInformationDTO(scraped_news=[])
        if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
            with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                results = executor.map(self._get_sitemap, news)
                for result in results:
                    if result:
                        if self.verbose:
                            logger.info(result)
                        news_data.append(result)

        else:
            for n in news:
                result = self._get_sitemap(n)
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)

        return NewsInformationDTO(scraped_news=news_data)

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        return url

    def get_news_in_bulk(self) -> List:
        soup = self.page_loader.get_soup(self.website_url)
        branches_to_crawl = self._get_branches(soup)
        links_to_crawl = []

        for branch_name, branch_link in branches_to_crawl.items():
            links = self._scrape(
                branch_link=branch_link,
                branch_name=branch_name
            )
            links_to_crawl.extend(links)
        logger.info(f"get {len(links_to_crawl)} to scrape for {self.website_name}")
        return links_to_crawl

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
                title = self._get_title(url)
                keywords = self._get_keywords(url)
                timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                new_branch_name = self._get_branch_name_from_url(link)
                branch_name = new_branch_name if new_branch_name != link else branch_name
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
    def _get_whole_text(soup):
        pass

    @staticmethod
    def _get_sitemap(articles_data: Dict[str, Any]) -> Union[SitemapDTO, None]:
        try:
            data_field_dict = {field: None for field in SitemapDTO.__dataclass_fields__.keys()}
            data_field_dict["headline"] = articles_data.get("headline")
            data_field_dict["keywords"] = articles_data.get("keywords")
            data_field_dict["timestamp"] = articles_data.get("timestamp")
            data_field_dict["category"] = articles_data.get("category")
            data_field_dict["link"] = articles_data.get("link")
            data_field_dict["sources"] = articles_data.get("sources")
            if data_field_dict["sources"] == WebsiteName.SUARA.name:
                data_field_dict["category"] = None

            return SitemapDTO(**data_field_dict)
        except pydantic.error_wrappers.ValidationError:
            logger.info(f"Error in get_content {articles_data.get('link')}. Reason: extracted_text is None")
            return None
        except BaseException as e:
            logger.info(f"Error in get_content {articles_data.get('link')}. Reason: {e}")
            return None

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_datetime

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        title = news_soup.find(news_title_element_name)
        if title:
            title = title.get_text(" ").strip()
            return title

    @staticmethod
    def _get_link(news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            if "?page=all" not in link:
                link += "?page=all"
            return link

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords
