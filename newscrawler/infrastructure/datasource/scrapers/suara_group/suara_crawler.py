import re
import logging
from typing import Dict


from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.infrastructure.datasource.scrapers.suara_group.suara_branch import (
    SuaraNetwork,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SuaraCrawler(Crawler):
    def __init__(self):
        super(SuaraCrawler, self).__init__()
        self.website_name = WebsiteName.SUARA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = SuaraNetwork().get_all_url()
        return branches

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://)(\w+)(\..*)", r"\2", url)
        if branch_name:
            return branch_name.strip()

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
        layer = soup.find("div", attrs={"class": ["detail--content"]})
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
