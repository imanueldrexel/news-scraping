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
                branch_name = re.sub(r"(https://)(.*)(\.okezone.*/sitemap.xml)", r"\2", link, )
                if branch_name == "www":
                    branch_name = "news"

                branches[branch_name] = link.strip()

        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"class": "read__content"})
        if not read_content_layer:
            read_content_layer = soup.find(
                "div", attrs={"class": "side-article txt-article"}
            )
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence and "Baca juga" not in sentence:
                    texts.append(sentence)
            return texts

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
