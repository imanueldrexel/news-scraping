import logging
import re
from typing import List, Dict

from newscrawler.core.importance_filter import SOURCE_SOFT_LEAVES
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.website_name import WebsiteName

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KompasCrawler(Crawler):
    # SRC-38 (#131): Kompas publishes three sitemap indexes. URL.KOMPAS
    # (news.kompas.com/news/sitemap.xml) lists only the ten news/regional
    # subdomains. Kompas Money, the finance desk, and www.kompas.com's own
    # sections had never been listed.
    EXTRA_INDEX_URLS = (
        "https://money.kompas.com/news/sitemap.xml",
        "https://www.kompas.com/sitemap.xml",
    )
    # <sub>.kompas.com/news/sitemap.xml -> key <sub> (the ten news hosts; the
    # stored categories keep their old names).
    _HOST_INDEX_RE = re.compile(r"^https?://([a-z0-9-]+)\.kompas\.com/news/sitemap\.xml$")
    # <host>.kompas.com/sitemap-news-<section>.xml -> key <section>. Only the
    # `sitemap-news-` leaves: `sitemap-basic` is static pages and
    # `sitemap-archive-*` is the back catalogue (SRC-45's rule).
    # Soft leaves no vocabulary word reaches, decided from 3 titles each (the
    # evidence is on the set's definition).
    SOFT_BRANCH_DENY = SOURCE_SOFT_LEAVES["KOMPAS"]
    _SECTION_LEAF_RE = re.compile(r"^https?://(?:www|money)\.kompas\.com/sitemap-news-([a-z0-9-]+)\.xml$")

    def __init__(self):
        super(KompasCrawler, self).__init__()
        self.website_name = WebsiteName.KOMPAS.value
        self.website_url = URL.KOMPAS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        """Handles all three index shapes. `re.match` and skip on no match, so a
        <loc> is never keyed by its URL (SRC-39)."""
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            link = loc.get_text(" ").strip()
            match = KompasCrawler._HOST_INDEX_RE.match(link) or KompasCrawler._SECTION_LEAF_RE.match(link)
            if match:
                branches.setdefault(match.group(1), link)
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
