import logging
import re
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class VivaCrawler(Crawler):
    def __init__(self):
        super(VivaCrawler, self).__init__()
        self.website_name = WebsiteName.VIVA.value
        self.website_url = URL.VIVA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "/news/" in link:
                    branch_name = re.sub(
                        r"(https://www.viva.co.id/sitemap/news/)(.*)(.xml)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_reporter_from_text(soup) -> List[str]:
        # SYS-08: VivaCrawler never implemented this, so every article's reporter
        # came back None (the unenforced abstract base method's implicit return),
        # which crashed NewsDetailsModel validation (reporter: List[str], not
        # Optional) and silently dropped every single VIVA article before it
        # could be saved -- 0 articles ever, despite the extractor working fine.
        reporters = []
        author_layer = soup.find("div", {"class": "main-content-author"})
        if author_layer:
            for link in author_layer.find_all("a"):
                name = link.get_text(" ").strip()
                if name:
                    reporters.append(name)
        return reporters

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find("div", {"class": "main-content-detail"})
        if article_layer:
            sentences = article_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" "))
                if sentence:
                    texts.append(sentence)
            return texts
