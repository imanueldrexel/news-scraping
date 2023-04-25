import re
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

    def _get_branches(self, soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "-sitemap.xml" not in link:
                    continue
                else:
                    soup = self.page_loader.get_soup(link)
                    if soup:
                        link = soup.find("loc")
                        if link:
                            link = link.get_text(" ").strip()
                            branch_name = re.sub(r"(.*)(//)(.*)(.tempo)(.*)", r"\3", link)
                            branch_name = branch_name.strip()
                            branches[branch_name] = link.strip()
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
