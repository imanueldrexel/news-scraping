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

_POST_SITEMAP = re.compile(r"^https://investor\.id/sitemap_post\.xml$")
_ARTICLE_URL = re.compile(r"^https://investor\.id/[a-z-]+/\d+/[^/?#]+")


class InvestorIDCrawler(Crawler):
    def __init__(self):
        super(InvestorIDCrawler, self).__init__()
        self.website_name = WebsiteName.INVESTORID.value
        self.website_url = URL.INVESTORID.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        """SRC-59 (#260): `soup` is investor.id's index (basic / post / news). The news sitemap
        answers 404 since 2026-10-06; the post sitemap holds the latest 100 articles, lastmod
        only (the base crawler's SYS-32 path). Keyed `news` as the old leaf was, so the stored
        category does not change. An index without it gives no branch, and the run fails with
        that reason instead of saving nothing quietly."""
        for loc in soup.find_all("loc"):
            url = loc.get_text(" ").strip()
            if _POST_SITEMAP.match(url):
                return {"news": url}
        return {}

    @classmethod
    def _link_has_article_id(cls, link: str) -> bool:
        """SRC-59: the post sitemap is lastmod-only, so a row's headline starts as the URL
        slug in words, and the article id is its own path segment
        (`/business/457702/medcoenergi-akuisisi-10-hak-partisipasi-eni`), not the slug's
        tail. Without this the slug ("Akuisisi 10 Hak") would stay the title instead of
        the page's ("Akuisisi 10% Hak")."""
        return bool(_ARTICLE_URL.match(link or ""))

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://investor.id/)(\w+)(/)(.*)", r"\2", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find("div", {"class": ["body-content"]})
        if article_layer:
            while article_layer.find_all("div"):
                article_layer.div.decompose()
            while article_layer.find_all("script"):
                article_layer.script.decompose()
            sentences = article_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text())
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": ["col small pt-1"]})
        if layer:
            reporter = layer.find("b")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporters.append(reporter.strip())
        return reporters
