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

    def _get_branches(self, soup) -> Dict[str, str]:
        """tirto.id is a two-level, lastmod-only structure: `soup` (from
        URL.TIRTO) lists per-section monthly sub-indexes; each of those lists
        one <sitemap> per month (also lastmod-only -- SYS-32, #94, handles
        that in the base crawler). Fetch ekonomi's and bisnis's sub-index and
        return each one's newest monthly leaf as the branch.
        """
        section_index_urls = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            url = loc.get_text(" ").strip()
            for section, suffix in _SECTION_URL_SUFFIXES.items():
                if url.endswith(suffix):
                    section_index_urls[section] = url

        branches = {}
        for section, section_index_url in section_index_urls.items():
            newest_leaf = self._newest_monthly_leaf(section_index_url)
            if newest_leaf:
                branches[section] = newest_leaf
        return branches

    def _newest_monthly_leaf(self, section_index_url: str) -> Optional[str]:
        section_soup = self.page_loader.get_soup(section_index_url)
        if not section_soup:
            return None
        newest_url, newest_dt = None, None
        for leaf in section_soup.find_all("sitemap"):
            leaf_loc = leaf.find("loc")
            leaf_lastmod = leaf.find("lastmod")
            if not leaf_loc or not leaf_lastmod:
                continue
            leaf_dt = self.date_time_reader.convert_date(leaf_lastmod.get_text(" ").strip())
            if leaf_dt and (newest_dt is None or leaf_dt > newest_dt):
                newest_url, newest_dt = leaf_loc.get_text(" ").strip(), leaf_dt
        return newest_url

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
