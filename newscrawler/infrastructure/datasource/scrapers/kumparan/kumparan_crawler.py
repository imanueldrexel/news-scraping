import logging
import re
from datetime import date
from typing import List, Tuple, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KumparanCrawler(Crawler):
    def __init__(self):
        super(KumparanCrawler, self).__init__()
        self.website_name = WebsiteName.KUMPARAN.value
        self.website_url = URL.KUMPARAN.value

    def _get_branches(self, soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap_channel_" in link:
                    branch_name = re.sub(r"(https://kumparan.com/sitemap_channel_)(.*)(.xml)", r"\2", link)
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup):
        sentences = soup.find(
            "span",
            attrs={
                "data-qa-id": "story-paragraph",
            },
        )
        texts = []
        for sentence in sentences:
            sentence = sentence.get_text(" ").strip()
            if sentence:
                texts.append(sentence)
        return texts

    def _get_reporter_from_text(self, soup) -> List[str]:

        reporters = []
        layers = soup.find_all("span", {"data-qa-id": "editor-name"})

        if layers:
            for layer in layers:
                reporter = layer.get_text(" ").strip()
                if reporter:
                    reporters.append(reporter)
        return reporters
