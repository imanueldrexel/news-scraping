import re
from typing import List, Dict

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


class TribunCrawler(Crawler):
    def __init__(self):
        super(TribunCrawler, self).__init__()
        self.website_name = WebsiteName.TRIBUN.value
        self.website_url = URL.TRIBUN.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        if sitemaps:
            for sitemap in sitemaps:
                link = sitemap.find("loc")
                if link:
                    link = link.get_text(" ").strip()
                    if "/sitemap-news" in link:
                        branch_name = re.sub(
                            r"(https://www.tribunnews.com/)(.*)(/sitemap-news.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                        branches[branch_name] = link.strip()
        return branches

    def _get_whole_text(self, soup) -> List[str]:
        multiple_pages = soup.find("div", attrs={"class": ["paging mb20"]})
        full_text = []
        if multiple_pages:
            pages = multiple_pages.find_all("a")
            for page in pages:
                link = page["href"]
                soup = self.page_loader.get_soup(link)
                texts = self._get_text(soup)
                if texts:
                    full_text.extend(texts)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = soup.find("div", attrs={"class": ["side-article", "txt-article"]})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                if sentence.attrs == {}:
                    sentence = preprocess_text(sentence.get_text(" ").strip())
                    sentence = re.sub(r"(\s+)(\1+)", r"\1", sentence)
                    texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        # SRC-09 (#57): TribunCrawler never implemented this, so it silently
        # inherited the base Crawler's no-op (returns None -- Crawler is a plain
        # class, not an ABC, so nothing enforced the override). Every article's
        # reporter=None crashed NewsDetailsModel construction (same class of bug as
        # VIVA/SYS-08). The byline lives in <div id="penulis">Penulis: <a>Name</a>
        # </div>; verified live across 5 categories (bisnis, nasional, regional,
        # seleb, techno) -- new-economy syndicated/wire content has no
        # individual byline at all (JSON-LD author is the "Tribunnews" org itself),
        # which correctly returns [] here, not a crash.
        reporters = []
        layer = soup.find("div", {"id": "penulis"})
        if layer:
            link = layer.find("a")
            name = link.get_text(" ").strip() if link else re.sub(
                r"^\s*Penulis\s*:\s*", "", layer.get_text(" ").strip(), flags=re.IGNORECASE
            ).strip()
            if name:
                reporters.append(name)
        return reporters
