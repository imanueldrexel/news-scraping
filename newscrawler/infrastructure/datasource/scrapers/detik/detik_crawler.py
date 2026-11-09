import re
import logging
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.core.importance_filter import SOURCE_SOFT_LEAVES
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DetikCrawler(Crawler):
    # The section path under any *.detik.com host -- `berita`, `bali/berita`,
    # `berita-ekonomi-bisnis`. Group 1 is what the previous re.sub produced as
    # `\4`, so every existing branch key is unchanged.
    _BRANCH_RE = re.compile(r"https?://[a-z0-9-]+\.detik\.com/(.+)/sitemap_news\.xml$")
    # DETIK's English edition, on its own domain (SRC-43 #146).
    _INDONESIANOW_RE = re.compile(r"https?://(?:www\.)?indonesianow\.co/(.+)/sitemap_news\.xml$")
    # SRC-50 (#162): 58 soft leaves no vocabulary word reaches, each decided from
    # 3 stored titles (the evidence is on the set's definition).
    SOFT_BRANCH_DENY = SOURCE_SOFT_LEAVES["DETIK"]

    def __init__(self):
        super(DetikCrawler, self).__init__()
        self.website_name = WebsiteName.DETIK.value
        self.website_url = URL.DETIK.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if not link:
                continue
            link = link.get_text(" ").strip()
            if "sitemap_news" not in link:
                continue
            match = DetikCrawler._BRANCH_RE.match(link)
            if match:
                branches[match.group(1).strip()] = link
                continue
            match = DetikCrawler._INDONESIANOW_RE.match(link)
            if match:
                # SRC-43 (#146): indonesianow.co is DETIK's English edition and
                # is not under .detik.com, so the old re.sub left these five
                # branches keyed by their URL and SRC-35's drop never saw them
                # -- including `lifestyle-and-entertainment`. Named by host so
                # the vocabulary can decide; sampled 2026-09-23 (Influenza
                # cases, KM Virgo SAR toll, Anak Krakatau alert) = real news,
                # in English, duplicating desks we already list -- the same
                # ground on which `english`/`english_edition` are dropped.
                branches["indonesianow/%s" % match.group(1)] = link
                continue
            # SRC-39: a <loc> this crawler cannot name is skipped, never keyed
            # by its URL.
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find("div", attrs={"class": "detail__body"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence in ["ADVERTISEMENT", "SCROLL TO RESUME CONTENT"]:
                    continue
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": ["detail__author"]})
        if layer:
            reporter = layer.get_text(" ")
            if reporter:
                reporter = reporter.split("-")[0]
                reporters.append(reporter.strip())
        return reporters
