import re
import logging
from typing import Dict, List

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
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
        self.website_name = WebsiteName.PIKIRANRAKYAT.value
        self.website_url = URL.PIKIRANRAKYAT.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = PikiranRakyatNetwork().get_all_url()
        return branches

    @staticmethod
    def _get_branch_name_from_url(url):
        branch_name = re.sub(
            r"(https://)(.*)(.pikiran-rakyat.com/)(\w+)(/pr.*)(.*)", r"\4", url
        )
        return branch_name

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

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        reporter = soup.find("div", attrs={"class": ["read__info__author"]})
        if reporter:
            reporter = reporter.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        return reporters
