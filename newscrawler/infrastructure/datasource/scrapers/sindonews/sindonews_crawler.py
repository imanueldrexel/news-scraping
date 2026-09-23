import re

from typing import Dict, List

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
    # SRC-46 (#156): one subdomain desk per sitemap.
    _BRANCH_RE = re.compile(r"https?://([a-z0-9-]+)\.sindonews\.com/sitemap\.xml$")

    def __init__(self):
        super(SindonewsCrawler, self).__init__()
        self.website_name = WebsiteName.SINDONEWS.value
        self.website_url = URL.SINDONEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        """SRC-46 (#156): `re.match` + skip, never `re.sub` -- a `<loc>` this
        crawler cannot name is skipped rather than keyed by its own URL, which
        `Crawler.is_soft_branch` can never match (SRC-39 #133).

        SINDONEWS publishes one sitemap per subdomain desk
        (`nasional.sindonews.com`, `ekbis.`, `scope.`, ...) plus eight
        site-wide `sitemap-*.xml` indexes that are not sections and are skipped
        by name, as before. The branch name is taken from the ORIGINAL `<loc>`
        and the `-news` variant built afterwards, so the name never depends on
        the rewrite. A no-op on today's index: all 12 desks still name
        themselves."""
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if not link:
                continue
            raw = link.get_text(" ").strip()
            if "sitemap-" in raw:
                continue
            match = SindonewsCrawler._BRANCH_RE.match(raw)
            if not match:
                continue
            branches[match.group(1)] = raw.replace("sitemap.xml", "sitemap-news.xml")

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
                attrs={
                    "class": ["article", "desc-artikel-detail", "detail-desc"],
                    "itemprop": None,
                },
            )
        if layer is None:
            layer = soup.find("section", attrs={"class": "article col-md-11"})

        if layer is None:
            layer = soup.find("div", attrs={"class": "list-article-scope"})

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

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", attrs={"class": "detail-nama-redaksi"})
        if layer:
            reporter = layer.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        else:
            layer = soup.find("div", attrs={"class": ["author-article"]})
            if layer:
                reporter = layer.find("strong")
                if reporter:
                    reporter = reporter.get_text(" ").strip()
                    reporters.append(reporter)
        return reporters
