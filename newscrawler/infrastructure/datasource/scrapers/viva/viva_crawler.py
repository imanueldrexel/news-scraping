import logging
import re
from typing import List, Dict

from newscrawler.core.importance_filter import SOURCE_SOFT_LEAVES
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

    # SRC-33 (#119): the live index (82 entries, 2026-09-26) has four shapes.
    #   www.viva.co.id/sitemap/news/<section>.xml       -> key <section> (Google-news leaf)
    #   <sub>.viva.co.id/sitemap/news/news-sitemap.xml  -> key <sub> (29 regional/
    #                                                      vertical sites)
    #   www.viva.co.id/sitemap/web/<section>.xml        -> skipped: the same URLs with
    #                                                      no news:title/date (bisnis:
    #                                                      1,000 = 1,000), SYS-32's
    #                                                      lastmod-only duplicate
    #   photo/foto/video/tag/channel, and www's news-sitemap.xml -> skipped; the
    #   aggregate's 1,000 URLs are all berita/gaya-hidup/bola/bisnis/otomotif/
    #   sport, which the sections already list.
    # The old re.sub returned the <loc> unchanged for every subdomain, so 29
    # branches (24,000 stored rows) were keyed, and stored as a category, by
    # their URL. re.match + skip, never a URL key (SRC-39).
    # Soft leaves no vocabulary word reaches, decided from 3 titles each.
    SOFT_BRANCH_DENY = SOURCE_SOFT_LEAVES["VIVA"]
    _SECTION_RE = re.compile(r"^https?://www\.viva\.co\.id/sitemap/news/([a-z0-9-]+)\.xml$")
    _SUBDOMAIN_RE = re.compile(r"^https?://([a-z0-9-]+)\.viva\.co\.id/sitemap/news/news-sitemap\.xml$")

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            link = loc.get_text(" ").strip()
            key = VivaCrawler.branch_name_from_url(link)
            if key:
                branches.setdefault(key, link)
        return branches

    @classmethod
    def branch_name_from_url(cls, value: str):
        """The branch key for a sitemap <loc>, or None to skip it. Also maps the
        URL-shaped categories the old re.sub stored (SRC-33) to today's key."""
        link = (value or "").strip()
        match = cls._SECTION_RE.match(link)
        if match:
            return None if match.group(1) == "news-sitemap" else match.group(1)
        match = cls._SUBDOMAIN_RE.match(link)
        if match and match.group(1) != "www":
            return match.group(1)
        return None

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
