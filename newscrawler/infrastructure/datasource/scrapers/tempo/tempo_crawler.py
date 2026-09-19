from typing import Dict, List

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


class TempoCrawler(Crawler):
    def __init__(self):
        super(TempoCrawler, self).__init__()
        self.website_name = WebsiteName.TEMPO.value
        self.website_url = URL.TEMPO.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        # SRC-06 (#17): the old implementation fetched all 28 -sitemap.xml
        # leaves up front (~155s -- this alone blew check_crawlers.py's 60s
        # budget) and mis-read each fetched leaf's first <loc> (an article
        # URL) as the branch link, collapsing 28 entries into a handful of
        # garbage keys derived from the article's own host. Target
        # ekonomi-sitemap.xml directly instead -- no extra fetch needed.
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if loc and loc.get_text(" ").strip().endswith("/ekonomi-sitemap.xml"):
                branches["ekonomi"] = loc.get_text(" ").strip()
        return branches

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": "paging"})
        full_text = []
        if multiple_pages:
            pages = multiple_pages.find_all("a")
            for page in pages:
                soup = self.page_loader.get_soup(page["href"])
                texts = self._get_text(soup)
                if texts:
                    full_text.extend(texts)
        else:
            full_text = self._get_text(soup)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = soup.find("div", attrs={"id": "isi"})
        if layer is None:
            layer = soup.find("div", attrs={"class", "detail-in"})
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence:
                    texts.append(sentence)

            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        reporter = soup.find("span", attrs={"itemprop": "author"})
        if reporter:
            reporter = reporter.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        editor = soup.find("span", attrs={"itemprop": "editor"})
        if editor:
            editor = editor.get_text(" ").strip()
            if editor:
                editor = editor.replace("Editor :", "")
                reporters.append(editor.strip())
        return reporters
