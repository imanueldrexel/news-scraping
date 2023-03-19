import logging
import os
import pickle
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import date
from typing import List, Dict, Union, Tuple

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
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

    def batch_crawling(self, news: List[Dict[str, str]]) -> NewsInformationDTO:
        news_data = []
        if not news:
            return NewsInformationDTO(scraped_news=[])
        if self.parallelize:
            with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                results = executor.map(self._get_content, news)
                for result in results:
                    if result:
                        if self.verbose:
                            logger.info(result)
                        news_data.append(result)

        else:
            for n in news:
                result = self._get_content(n)
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)

        return NewsInformationDTO(scraped_news=news_data)

    @abstractmethod
    def get_news_in_bulk(
        self, last_crawling_time: Dict[str, date]
    ) -> Tuple[Dict[str, any], List[Dict[str, any]]]:
        raise NotImplementedError

    @staticmethod
    def _get_whole_text(soup):
        pass

    def _get_content(self, articles_data) -> Union[NewsDetailsDTO, None]:
        url = articles_data.get("link")
        try:
            soup = self.page_loader.get_soup(url)
            data_field_dict = {
                field: None for field in NewsDetailsDTO.__dataclass_fields__.keys()
            }

            data_field_dict["extracted_text"] = self._get_whole_text(soup)
            data_field_dict["headline"] = articles_data.get("headline")
            data_field_dict["keywords"] = articles_data.get("keywords")
            data_field_dict["timestamp"] = articles_data.get("timestamp")
            data_field_dict["category"] = articles_data.get("category")
            data_field_dict["link"] = articles_data.get("link")
            data_field_dict["sources"] = articles_data.get("sources")

            if data_field_dict["sources"] == WebsiteName.SUARA.name:
                data_field_dict["category"] = self._get_category(soup)

            return NewsDetailsDTO(**data_field_dict)
        except pydantic.error_wrappers.ValidationError:
            logger.info(f"Error in get_content {url}. Reason: extracted_text is None")
            return None
        except AttributeError as e:
            logger.info(f"Error in get_content {url}. Reason: {e}")
            return None

    def get_last_crawling_time(self) -> Dict[str, date]:
        try:
            pickle_name = f"{self.website_name.lower()}.pkl"
            pickle_path = os.path.join(self.main_path, pickle_name)
            file = open(pickle_path, "rb")
            last_crawling_time = pickle.load(file)
            return last_crawling_time
        except IOError:
            return {}
        except BaseException as e:
            logger.info(f'Fail to open last crawling time pickle file. Reason: {e}')

    def set_last_crawling_time(
        self,
        last_crawling_time: Union[Dict[str, str], None]
    ) -> None:
        try:
            pickle_name = f"{self.website_name.lower()}.pkl"
            pickle_path = os.path.join(self.main_path, pickle_name)
            file = open(pickle_path, "wb")
            pickle.dump(last_crawling_time, file)
            logger.info(f"Successfully save the data into {pickle_path}")
        except BaseException as e:
            logger.error(f"Fail to save the data to dump file.\n Reason: {e}")

    @staticmethod
    def _get_delta_and_delta_in_second(
        timestamp, last_crawling, date_time_reader: DateTimeReader
    ):
        time_posted = timestamp.replace("T", " ").replace("+07:00", "")
        time_posted = date_time_reader.convert_date(time_posted)
        delta = time_posted - last_crawling
        delta_in_seconds = delta.days * 86400 + delta.seconds
        return time_posted, delta, delta_in_seconds

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_string, timestamp_datetime

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
            link = link+"?page=all"
            return link

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords

    @staticmethod
    def _get_category(news_soup) -> str:
        raise NotImplementedError
