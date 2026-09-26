import logging
import re
from typing import List, Dict, Optional

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


# SRC-53 (#173): a www.inews.id section sitemap -- /<section>[/<leaf>...]/sitemap.xml.
# Regional subdomains (<city>.inews.id) do not match: SRC-29 retired them.
_WWW_SECTION = re.compile(r"^https?://www\.inews\.id/([a-z0-9-]+(?:/[a-z0-9-]+)*)/sitemap\.xml$")


class INewsCrawler(Crawler):
    # Soft leaves no vocabulary word reaches, decided from sampled titles (SRC-53).
    SOFT_BRANCH_DENY = SOURCE_SOFT_LEAVES["INEWS"]

    @staticmethod
    def branch_name_from_url(link: str) -> Optional[str]:
        """The section name of a www.inews.id section sitemap -- its path without
        `/sitemap.xml` (`inews-tv/talkshow`) -- or None when this crawler cannot
        name it. Never the URL itself (SRC-39).

        `scripts/fix_url_shaped_categories.py` uses it to rename the rows stored
        under a URL before SRC-27 (#109). `_get_branches` still keys its one
        finance leaf `finance`, the name its rows are stored under. When SRC-34
        (#124) widens INEWS it should key every section with this function, so
        stored categories cannot drift from the live keys."""
        match = _WWW_SECTION.match((link or "").strip())
        return match.group(1) if match else None

    def __init__(self):
        super(INewsCrawler, self).__init__()
        self.website_name = WebsiteName.INEWS.value
        self.website_url = URL.INEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        # SRC-27 (#109): the real index has 129 entries -- www.inews.id's own
        # topical sections (finance, sport, lifestyle, ...) plus 113 regional
        # subdomains (bogor.inews.id, etc.). The old code kept every one of
        # them; a real run ingested 24,861 sitemaps, 90% from those regional
        # subdomains, 98% of which 404 (dead mirrors). Keep only the finance
        # leaf -- see DBT-04 for widening to other sections.
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if link and link.get_text(" ").strip().endswith("/finance/bisnis/sitemap.xml"):
                branches["finance"] = link.get_text(" ").strip()
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
                    if (
                        sentence
                        and "Baca juga" not in sentence
                        and "Editor :" not in sentence
                        and "Bagikan Artikel:" not in sentence
                    ):
                        texts.append(sentence)
            return texts
        else:
            read_content_layer = soup.find("div", attrs={"class": "caption"})
            if read_content_layer:
                sentences = read_content_layer.find_all("p")
                texts = []
                for sentence in sentences:
                    if sentence.attrs == {}:
                        sentence = preprocess_text(sentence.get_text(" ").strip())
                        if (
                            sentence
                            and "Baca juga" not in sentence
                            and "Editor :" not in sentence
                            and "Bagikan Artikel:" not in sentence
                        ):
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
                    reporter = reporter["title"]
                    if reporter:
                        reporter = reporter.strip()
                        reporters.append(reporter)
        return reporters
