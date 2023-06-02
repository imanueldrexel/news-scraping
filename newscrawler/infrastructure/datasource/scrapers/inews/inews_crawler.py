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


class INewsCrawler(Crawler):
    def __init__(self):
        super(INewsCrawler, self).__init__()
        self.website_name = WebsiteName.INEWS.value
        self.website_url = URL.INEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                branch_name = re.sub(r"(https://)(\w+)(\.inews.id.*)", r"\2", link)
                if branch_name == "www":
                    branch_name = re.sub(r"(https://www.inews.id/)(\w+)(/)(.*)", r"\2", link)

                branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"itemprop": "articleBody"})
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                if sentence.attrs == {}:
                    sentence = preprocess_text(sentence.get_text(" ").strip())
                    if sentence and "Baca juga" not in sentence and "Editor :" not in sentence and "Bagikan Artikel:" not in sentence:
                        texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", attrs={"class": "author"})
        for reporter in layers:
            reporter = reporter.find("a")
            if reporter:
                reporter = reporter.find("img")
                if reporter:
                    reporter = reporter['title']
                    if reporter:
                        reporter = reporter.strip()
                        reporters.append(reporter)
        return reporters
