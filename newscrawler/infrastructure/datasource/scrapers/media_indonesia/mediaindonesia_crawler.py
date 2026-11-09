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


class MediaIndonesiaCrawler(Crawler):
    # `https://mediaindonesia.com/sitemap-<name>.xml` -> <name> (SRC-43 #146).
    _BRANCH_RE = re.compile(r"https?://[^/]+/sitemap-([a-z0-9-]+)\.xml$")

    def __init__(self):
        super(MediaIndonesiaCrawler, self).__init__()
        self.website_name = WebsiteName.MEDIAINDONESIA.value
        self.website_url = URL.MEDIAINDONESIA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        """SRC-43 (#146): MEDIAINDONESIA's index is flat --
        `https://mediaindonesia.com/sitemap-<name>.xml` -- so the old
        `https://[^/]+/([^/]+)/.*` pattern, which needs a second path segment,
        never matched and re.sub returned the URL unchanged. All 283 branches
        were keyed by their URL, which is why `check_crawlers` reported
        `soft_branches=0` for this source: SRC-35's word-bounded drop cannot
        match a URL, so it was reporting "nothing soft here" about a source it
        could not read at all.

        The names are `news`, `category`, `video`, `article-YYYY-MM` and
        `gallery-YYYY-MM`. Naming them changes nothing about what is listed --
        none of those words is in SOFT_BRANCH_WORDS -- it makes the source
        legible to the one enforcement point. Whether the date-partitioned
        archives and the photo galleries should be listed at all is a scope and
        volume decision with its own evidence, filed separately (SRC-45 #155):
        only `sitemap-news.xml` carries news:title, and the galleries are
        `detail_galleries` photo pages.
        """
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if not link:
                continue
            link = link.get_text(" ").strip()
            match = MediaIndonesiaCrawler._BRANCH_RE.match(link)
            if not match:
                # SRC-39: a <loc> this crawler cannot name is skipped.
                continue
            branches[match.group(1)] = link
        return branches

    # SRC-48 (#158): the article's own section, e.g.
    # https://mediaindonesia.com/olahraga/936920/jorge-martin-... -> `olahraga`.
    # The previous implementation was
    #   re.sub(r"(https://www.mediaindonesia.com/)(.*)(/)", r"\1", url)
    # which substituted group 1 (the host prefix) and required a `www.` the live
    # URLs do not have, so it returned its input unchanged -- a URL-shaped
    # category, the damage SRC-36/SRC-41 repaired 6,104 rows for. Since
    # MEDIAINDONESIA's only news-format sitemap is one mixed feed, this is the
    # single thing that lets the category gate reject its soft sections.
    _SECTION_RE = re.compile(r"https?://(?:www\.)?mediaindonesia\.com/([a-z0-9-]+)/")

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        match = MediaIndonesiaCrawler._SECTION_RE.match(url or "")
        # None on no match: the base `_scrape` then falls back to the branch
        # name rather than storing something unusable (SRC-48).
        return match.group(1) if match else None

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find("div", {"class": "article"})
        if article_layer:
            sentences = article_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text())
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        reporter = soup.find("div", attrs={"class": "author", "style": None})
        if reporter:
            reporter.a.decompose()
            reporter = reporter.get_text(" ").strip()
            if reporter:
                reporter = reporter.replace(" |")
                reporters.append(reporter)
        return reporters
