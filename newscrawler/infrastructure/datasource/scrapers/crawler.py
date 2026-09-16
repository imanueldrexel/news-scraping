import logging
import os
import re
from newspaper import Article
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Dict, Union, Any, Tuple

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER, MIN_ARTICLE_CHARS
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
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

    def batch_crawling_sitemap(
        self, news: List[Dict[str, str]], website_name: str
    ) -> List[SitemapDTO]:
        news_data = []
        if news:
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

        return news_data

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        return "news"

    def get_news_in_bulk(self) -> List:
        soup = self.page_loader.get_soup(self.website_url)
        if not soup:
            logger.warning(f"Could not load sitemap from {self.website_url}")
            return []
            
        branches_to_crawl = self._get_branches(soup)
        links_to_crawl = []
        
        for branch_name, branch_link in branches_to_crawl.items():
            links = self._scrape(branch_link=branch_link, branch_name=branch_name)
            links_to_crawl.extend(links)
        return links_to_crawl

    def _scrape(self, branch_link, branch_name) -> List:
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
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    "category": new_branch_name if branch_name == link else branch_name,
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
            data_field_dict = {
                field: None for field in SitemapDTO.__dataclass_fields__.keys()
            }
            data_field_dict["headline"] = articles_data.get("headline")
            data_field_dict["keywords"] = articles_data.get("keywords")
            data_field_dict["timestamp"] = articles_data.get("timestamp")
            data_field_dict["category"] = articles_data.get("category")
            data_field_dict["link"] = articles_data.get("link")
            data_field_dict["sources"] = articles_data.get("sources")
            if data_field_dict["sources"] == WebsiteName.SUARA.name:
                data_field_dict["category"] = None
            return SitemapDTO(**data_field_dict)
        except BaseException as e:
            logger.info(
                f"Error in get_content {articles_data.get('link')}. Reason: {e}"
            )
            return None

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            timestamp_datetime = date_time_reader.convert_date(timestamp_string)
            return timestamp_datetime.astimezone(date_time_reader.gmt_offset)

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        title = news_soup.find(news_title_element_name)
        if title:
            title = title.get_text(" ").strip()
            return title

    def _get_link(self, news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            if "?page=all" not in link and self.website_name != "JPNN":
                link += "?page=all"
            return link

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            keywords = [x.strip() for x in keywords.split()]
            return keywords

    def batch_crawling_details(
        self, news: List[SitemapDTO], website_name: str
    ) -> List[NewsDetailsDTO]:
        news_data = []
        if news:
            if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
                with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                    results = executor.map(self._get_news_details, news)
                    for result in results:
                        if result:
                            if self.verbose:
                                logger.info(result)
                            news_data.append(result)

            else:
                for n in news:
                    result = self._get_news_details(n)
                    if result:
                        if self.verbose:
                            logger.info(result)
                        news_data.append(result)

        return news_data

    def _get_news_details(self, sitemap: SitemapDTO) -> NewsDetailsDTO:
        try:
            url = sitemap.link
            if self.website_name == "JPNN":
                url = sitemap.link.replace("?page=all", "")
            soup = self.page_loader.get_soup(url)
            if soup:
                # Site extractors are hand-written selectors that raise (typically
                # AttributeError on a missing container) when the layout drifts. A crash
                # must count as "extractor failed", not discard the article, so the
                # fallback chain still runs and the sitemap still gets marked attempted.
                try:
                    reporter = self._get_reporter_from_text(soup)
                except Exception as r_err:
                    logger.warning(f"Reporter extraction raised for {url}: {r_err!r}")
                    reporter = []
                try:
                    extracted_text = self._get_whole_text(soup)
                except Exception as x_err:
                    logger.warning(f"Site extractor raised for {url}: {x_err!r}")
                    extracted_text = None

                # Site extractors return None when their container is missing and [] when
                # it exists but no paragraph matched (layout drift). Both, and anything
                # shorter than MIN_ARTICLE_CHARS, must fall through to the next extractor.
                if not self._has_usable_text(extracted_text):
                    logger.info(f"Standard extraction failed for {url}. Attempting Trafilatura fallback...")
                    extracted_text = self._best_of(extracted_text, self._trafilatura_fallback(soup))

                if not self._has_usable_text(extracted_text):
                    extracted_text = self._best_of(extracted_text, self._newspaper_fallback(url))

                if not self._has_usable_text(extracted_text):
                    logger.warning(
                        f"All extractors returned empty or too-short text for {url} "
                        f"({self._text_length(extracted_text)} chars)"
                    )

                meta_data = {"title": sitemap.headline, "posted_at": sitemap.timestamp}
                return NewsDetailsDTO(
                    sitemap_id=sitemap.sitemap_id,
                    extracted_text=extracted_text,
                    reporter=reporter,
                    meta_data=meta_data,
                )
        except BaseException as e:
            logger.info(f"Error in get_content {sitemap.link}. Reason: {e}")

    @staticmethod
    def _text_length(extracted_text) -> int:
        """Total characters in an extraction result (None, str, or list of paragraphs)."""
        if not extracted_text:
            return 0
        if isinstance(extracted_text, str):
            return len(extracted_text.strip())
        return sum(len(p.strip()) for p in extracted_text if p)

    @classmethod
    def _has_usable_text(cls, extracted_text) -> bool:
        length = cls._text_length(extracted_text)
        return length > 0 and length >= MIN_ARTICLE_CHARS

    @classmethod
    def _best_of(cls, current, candidate):
        """Keep whichever extraction result has more text, so a failed fallback never
        replaces a short-but-real result with nothing."""
        return candidate if cls._text_length(candidate) > cls._text_length(current) else current

    @staticmethod
    def _trafilatura_fallback(soup) -> Union[List[str], None]:
        try:
            import trafilatura
            text = trafilatura.extract(str(soup))
        except Exception as t_err:
            logger.warning(f"Trafilatura fallback failed: {t_err}")
            return None
        if not text:
            return None
        logger.info("Trafilatura extraction successful.")
        # Split into paragraphs to match the shape site extractors return.
        return text.split("\n\n")

    @staticmethod
    def _newspaper_fallback(url) -> Union[List[str], None]:
        try:
            article = Article(url)
            article.download()
            article.parse()
        except Exception as n_err:
            logger.warning(f"Newspaper fallback failed: {n_err}")
            return None
        return article.text.split("\n\n") if article.text else None

    @abstractmethod
    def _get_reporter_from_text(self, soup) -> List[str]:
        pass
