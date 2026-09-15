import logging
import re
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.website_name import WebsiteName

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OkezoneCrawler(Crawler):
    def __init__(self):
        super(OkezoneCrawler, self).__init__()
        self.website_name = WebsiteName.OKEZONE.value
        self.website_url = URL.OKEZONE.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                branch_name = re.sub(
                    r"(https://)(.*)(\.okezone.*/sitemap.xml)",
                    r"\2",
                    link,
                )
                if branch_name == "www":
                    branch_name = "news"

                branches[branch_name] = link.strip()

        return branches

    def _get_whole_text(self, soup) -> List[str]:
        texts = []
        while soup:
            text_first_page = self._get_text(soup)
            if text_first_page:
                texts.extend(text_first_page)
            next_button_soup = soup.find("div", attrs={"class": "next"})
            if next_button_soup:
                next_page_link = next_button_soup.find("a")

                current_page = soup.find("div", attrs={"class": "first-paging"})
                current_page = (
                    int(current_page.get_text(" "))
                    if current_page and int(current_page.get_text(" "))
                    else 1
                )
                max_page = soup.find("div", attrs={"class": "second-paging"})
                max_page = (
                    int(max_page.get_text(" ")) if int(max_page.get_text(" ")) else 1
                )
                if next_page_link and (max_page / current_page) != 1:
                    next_page_link = next_page_link["href"]
                    soup = self.page_loader.get_soup(next_page_link)
                else:
                    break
        return texts

    @staticmethod
    def _get_text(soup) -> List[str]:
        soup = soup.find("div", attrs={"class": "detail detail__billboard class-vidy"})
        layer = soup.find(
            "div", attrs={"itemprop": "articleBody", "class": "read", "id": "contentx"}
        )
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences[:1]:
                divs = sentence.find_all("div")
                for div in divs:

                    if div.attrs == {"class": ["first-paging"]} or div.attrs == {
                        "class": ["second-paging"]
                    }:

                        continue
                    else:
                        div.decompose()
                divs = sentence.find_all("div")

                if sentence.attrs != {}:
                    continue
                extracted_text = preprocess_text(sentence.text.strip())
                if len(extracted_text) > 0:
                    texts.append(extracted_text)

            return texts

        # read_content_layer = soup.find("div", attrs={"class": "read__content"})
        # if not read_content_layer:
        #     read_content_layer = soup.find(
        #         "div", attrs={"class": "side-article txt-article"}
        #     )
        # if read_content_layer:
        #     sentences = read_content_layer.find_all("p")
        #     texts = []
        #     for sentence in sentences:
        #         sentence = preprocess_text(sentence.get_text(" ").strip())
        #         if sentence and "Baca juga" not in sentence:
        #             texts.append(sentence)
        #     return texts

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
