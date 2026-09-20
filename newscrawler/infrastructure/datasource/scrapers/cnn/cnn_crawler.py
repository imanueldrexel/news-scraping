import re
import logging
from typing import List, Dict, Optional

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# SRC-36 (#129): the live index (2026-09-20) lists one Google-news leaf per
# section, one path segment deep -- `/nasional/sitemap_news.xml` -- next to a
# `sitemap_web.xml`/`sitemap_video.xml` twin per section and a `tv/` video-only
# entry. Anything that isn't exactly `<section>/sitemap_news.xml` is skipped.
_NEWS_LEAF = re.compile(r"^https://www\.cnnindonesia\.com/([^/]+)/sitemap_news\.xml$")
# Carried over from the pre-SRC-36 code, which excluded it by substring; not
# in the live index today, so it has never been sampled. If it reappears, the
# SRC-35 per-leaf 3-title review decides it, not this set.
_SKIP_SECTIONS = {"longform"}


class CNNCrawler(Crawler):
    def __init__(self):
        super(CNNCrawler, self).__init__()
        self.website_name = WebsiteName.CNN.value
        self.website_url = URL.CNN.value

    @staticmethod
    def branch_name_from_url(link: str) -> Optional[str]:
        """The branch key for a sitemap-index <loc>, or None when this crawler
        cannot name it. The single decision both `_get_branches` and the
        SRC-36 category repair (`scripts/fix_url_shaped_categories.py`) use,
        so the stored `sitemaps.category` cannot drift from the live key."""
        match = _NEWS_LEAF.match(link.strip())
        if not match or match.group(1) in _SKIP_SECTIONS:
            return None
        return match.group(1)

    @classmethod
    def _get_branches(cls, soup) -> Dict[str, str]:
        # SRC-36 (#129): the old regex wanted two path segments before
        # sitemap_news.xml; the live index has one, so re.sub never matched
        # and returned the link unchanged -- every branch was keyed by its
        # own full URL, every sitemaps.category for CNN was a URL, and the
        # exact-match half of the category deny-list (gaya-hidup) was blind
        # to it. Third instance of the SRC-14/SRC-33 shape: never key a
        # branch by a URL; a <loc> this crawler cannot name is skipped.
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            link = loc.get_text(" ").strip()
            name = cls.branch_name_from_url(link)
            if name is None:
                continue
            branches[name] = link
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find("div", attrs={"class": "detail_text"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        return []
