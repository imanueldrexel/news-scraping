import logging
from datetime import datetime, timedelta, timezone
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

# SRC-16 (#95): the section sub-indexes to keep from the ~42 in URL.TIRTO's
# index (flash-news/politik, diajeng, edusains, ... are the other 40, all
# off-topic per SYS-31). Never sitemap_latest.xml -- that's every section
# merged, same trap.
_SECTION_URL_SUFFIXES = {
    "ekonomi": "/insider/ekonomi.xml",
    "bisnis": "/insider/bisnis.xml",
}


class TirtoCrawler(Crawler):
    def __init__(self):
        super(TirtoCrawler, self).__init__()
        self.website_name = WebsiteName.TIRTO.value
        self.website_url = URL.TIRTO.value

    # SRC-32 (#117): a monthly leaf is still read while its <lastmod> is this
    # recent. The sub-index is one leaf per calendar month, so a newest-leaf-only
    # rule stopped reading August on the first September article and silently
    # never listed what August published after the last crawl of the month
    # (its leaf's lastmod was 08-31 19:10). Two weeks covers the month boundary
    # with a wide margin over the twice-daily schedule; re-listing a leaf costs
    # one fetch, since sitemaps dedup on the link (SYS-29).
    RECENT_LEAF_DAYS = 14

    def _get_branches(self, soup) -> Dict[str, str]:
        """tirto.id is a two-level, lastmod-only structure: `soup` (from
        URL.TIRTO) lists per-section sub-indexes, and each of those lists one
        <sitemap> leaf per month (also lastmod-only -- SYS-32, #94, handles
        that in the base crawler). A branch is the SECTION: its key is the
        section name (stored as the category) and its link the section's
        sub-index. `_scrape` expands it to the leaves worth reading.
        """
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            url = loc.get_text(" ").strip()
            for section, suffix in _SECTION_URL_SUFFIXES.items():
                if url.endswith(suffix):
                    branches[section] = url
        return branches

    def _scrape(self, branch_link, branch_name) -> List:
        """SRC-32: every recent monthly leaf of the section, under the one
        section name."""
        articles = []
        for leaf in self._recent_monthly_leaves(branch_link):
            articles.extend(super()._scrape(branch_link=leaf, branch_name=branch_name))
        return articles

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _recent_monthly_leaves(self, section_index_url: str) -> List[str]:
        """The newest leaf, plus every other leaf modified within
        RECENT_LEAF_DAYS, newest first. A section index that does not load is
        logged and yields nothing -- the other sections still stand."""
        section_soup = self.page_loader.get_soup(section_index_url)
        if not section_soup:
            logger.warning(f"{self.website_name}: could not load section index {section_index_url}")
            return []
        dated = []
        for leaf in section_soup.find_all("sitemap"):
            leaf_loc = leaf.find("loc")
            leaf_lastmod = leaf.find("lastmod")
            if not leaf_loc or not leaf_lastmod:
                continue
            leaf_dt = self.date_time_reader.convert_date(leaf_lastmod.get_text(" ").strip())
            if leaf_dt:
                dated.append((leaf_dt, leaf_loc.get_text(" ").strip()))
        if not dated:
            return []
        dated.sort(reverse=True)
        cutoff = self._now() - timedelta(days=self.RECENT_LEAF_DAYS)
        return [dated[0][1]] + [url for dt, url in dated[1:] if dt >= cutoff]

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find_all("div", {"class": "content-text-editor"})
        if article_layer:
            texts = []
            for sentence in article_layer[1:]:
                while sentence.find_all("script"):
                    sentence.script.decompose()
                while sentence.find_all("div"):
                    sentence.div.decompose()
                sentence = preprocess_text(sentence.get_text(" ")).split(". ")
                texts.extend(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find("div", {"class": "credit"})
        if layer:
            reporters_layers = soup.find_all("span", {"class": "reporter-grup"})
            for reporters_layer in reporters_layers:
                reporter = reporters_layer.get_text(" ").strip()
                if reporter:
                    reporter = (
                        reporter.replace("Kontributor: ", "")
                        .replace("Penulis: ", "")
                        .replace("Editor: ", "")
                    )
                    if reporter:
                        reporters.append(reporter)
        return list(set(reporters))
