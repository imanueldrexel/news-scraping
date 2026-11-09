import logging
from typing import Dict, List

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SuaraCrawler(Crawler):
    # DBT-05 (#24): this source's site selector had been dead for months (trafilatura
    # produced every saved article); trafilatura is its extractor by design.
    PRIMARY_EXTRACTOR = "trafilatura"

    def __init__(self):
        super(SuaraCrawler, self).__init__()
        self.website_name = WebsiteName.SUARA.value
        # SRC-12 (#90): never set before -- _get_branches used to ignore the
        # fetched index entirely (a hardcoded regional branch list instead),
        # so nothing ever read this. get_news_in_bulk() needs it now.
        self.website_url = URL.SUARA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        # SRC-12 (#90): the old branch list was 20 hardcoded SuaraNetwork
        # regional sitemaps, all frozen at 2022-10-23 -- never read from the
        # site's actual index. The real index is a standard sitemapindex of
        # <section>/sitemap-{news,web,image}.xml entries; keep bisnis's news
        # leaf (the finance-relevant one -- see DBT-04 for widening this).
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if loc and "/bisnis/sitemap-news.xml" in loc.get_text(" ").strip():
                branches["bisnis"] = loc.get_text(" ").strip()
        return branches

    @staticmethod
    def _get_text(soup):
        layer = soup.find("article", attrs={"class": "detail-content"})
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
        reporter = soup.find("div", attrs={"class": "writer"})
        if reporter:
            reporter = reporter.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        return list(set(reporters))
