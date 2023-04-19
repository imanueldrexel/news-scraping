import re

from typing import Dict

from bs4.element import NavigableString

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SindonewsCrawler(Crawler):
    def __init__(self):
        super(SindonewsCrawler, self).__init__()
        self.website_name = WebsiteName.SINDONEWS.value
        self.website_url = URL.SINDONEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link and "sitemap-" not in link.get_text(" "):
                link = link.get_text(" ").strip()
                link = link.replace("sitemap.xml", "sitemap-news.xml")
                branch_name = re.sub(r"(.*)(//)(.*)(.sindonews)(.*)", r"\3", link)
                branch_name = branch_name.strip()
                branches[branch_name] = link

        return branches

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": ["content-show"]})
        full_text = []
        if multiple_pages:
            show_all = multiple_pages.find("a")
            if show_all:
                show_all = show_all["href"]
                soup = self.page_loader.get_soup(show_all)
                full_text = self._get_text(soup)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = None
        if layer is None:
            layer = soup.find(
                "div", attrs={"itemprop": ["articleBody"], "class": ["caption", None]}
            )
        if layer is None:
            layer = soup.find(
                "div",
                attrs={"class": ["article", "desc-artikel-detail", "detail-desc"], "itemprop": None},
            )
        if layer is None:
            layer = soup.find("section", attrs={"class": "article col-md-11"})

        layer_contents = sorted(layer.contents, key=lambda x: len(x), reverse=True)[0]
        if not isinstance(layer_contents, NavigableString):
            layer = layer_contents
        texts = []
        text = ""
        for x in layer.contents:
            if type(x) == NavigableString:
                tmp_text = preprocess_text(x.strip())
                text += " " + tmp_text
            else:
                avoided_keyword = [
                    "Baca Juga",
                    "Baca juga",
                    "Lihat Juga",
                    "Lihat juga",
                    "Penulis:",
                    "Penulis :",
                    "Reporter:",
                    "Simak berita lainnya seputar",
                    "Bergabung dan dapatkan analisis informasi",
                ]
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in x.get_text(" "):
                        continue_sentence = 1
                if continue_sentence:
                    continue
                else:
                    tmp_text = preprocess_text(x.get_text(" ").strip())
                    text += " " + tmp_text

        for sentence in text.split(". "):
            sentence = sentence.strip()
            if sentence:
                texts.append(sentence)
        return texts
