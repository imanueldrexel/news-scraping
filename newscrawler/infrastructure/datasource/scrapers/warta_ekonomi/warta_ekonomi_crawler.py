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


class WartaEkonomiCrawler(Crawler):
    def __init__(self):
        super(WartaEkonomiCrawler, self).__init__()
        self.website_name = WebsiteName.WARTAEKONOMI.value
        self.website_url = URL.WARTAEKONOMI.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "/news/" in link:
                    try:
                        branch_name = re.sub(r"(https://wartaekonomi.co.id/news/news-)(\w+)(.*)", r"\2", link)
                    except BaseException :
                        branch_name = "news"
                    branches[branch_name] = link.strip()
        return branches

    def _get_whole_text(self, soup) -> List[str]:
        layer = soup.find("div", attrs={"class": "articlePostContent"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                divs = sentence.find_all("div")
                for div in divs:
                    div.decompose()
                if sentence.attrs != {}:
                    continue
                extracted_text = preprocess_text(sentence.text.strip())
                if len(extracted_text) > 0 and "Baca Juga:" not in extracted_text:
                    texts.append(extracted_text)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = set()
        layers = soup.find_all("div", attrs={"class": "articlePostAuthor"})
        for reporter in layers:
            reporter = reporter.find("p")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporter = reporter.replace("Penulis:", '')
                    reporter = reporter.replace("Editor:", '')
                    reporter = reporter.strip()
                    reporter = reporter.split("\n")
                    for r in reporter:
                        reporters.add(r.strip())

        return list(reporters)
