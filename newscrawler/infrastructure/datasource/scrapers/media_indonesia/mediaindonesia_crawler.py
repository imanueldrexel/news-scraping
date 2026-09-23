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

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://www.mediaindonesia.com/)(.*)(/)", r"\1", url)
        if branch_name:
            return branch_name.strip()

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
