import logging
import os
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Dict, Union

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Crawler:
    def __init__(self):
        self.verbose = VERBOSE
        self.parallelize = PARALLELIZE
        self.date_time_reader = DateTimeReader()
        self.default_time = self.date_time_reader.convert_date("2000-01-01 00:00:01")
        self.max_worker = MAX_WORKER
        self.page_loader = RequestsPageLoader()

    @abstractmethod
    def get_news_data(self, web_url: str) -> NewsInformationDTO:
        pass

    def batch_crawling(self, news: List[Dict[str, str]]) -> List[NewsDetailsDTO]:
        news_data = []
        if not news:
            return news_data
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

        return news_data

    @staticmethod
    def _get_whole_text(soup):
        pass

    def _get_content(self, articles_data) -> Union[NewsDetailsDTO, None]:
        url = articles_data.get('link')
        try:
            soup = self.page_loader.get_soup(url)
            data_field_dict = {field: None for field in NewsDetailsDTO.__dataclass_fields__.keys()}

            data_field_dict["extracted_text"] = self._get_whole_text(soup)
            data_field_dict["headline"] = articles_data.get('headline')
            data_field_dict["keywords"] = articles_data.get('keywords')
            data_field_dict["timestamp"] = articles_data.get('timestamp')
            data_field_dict["category"] = articles_data.get('category')
            data_field_dict["link"] = articles_data.get('link')
            data_field_dict["sources"] = articles_data.get('sources')

            return NewsDetailsDTO(**data_field_dict)
        except pydantic.error_wrappers.ValidationError:
            logger.info(f'Error in get_content {url}. Reason: extracted_text is None')
            return None
        except AttributeError as e:
            logger.info(f'Error in get_content {url}. Reason: {e}')
            return None
