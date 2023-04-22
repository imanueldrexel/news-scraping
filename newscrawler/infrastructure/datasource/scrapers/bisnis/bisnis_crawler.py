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


class BisnisCrawler(Crawler):
    def __init__(self):
        super(BisnisCrawler, self).__init__()
        self.website_name = WebsiteName.BISNIS.value
        self.website_url = URL.BISNIS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap-news" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.bisnis)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(
                            r"(https://www.bisnis.com/)(.*)(/sitemap-news.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        layer = soup.find(
            "div",
            attrs={"itemprop": ["articleBody"], "class": ["col-sm-10", "copas", None]},
        )
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences:
                avoided_keyword = [
                    "Baca Juga",
                    "Baca juga",
                    "Lihat Juga",
                    "Lihat juga",
                    "Penulis:",
                    "Penulis :",
                    "Reporter:",
                    "Simak berita lainnya seputar",
                    "Bergabung dan dapatkan analisis informasi",
                ]
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in sentence.get_text(" "):
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if not sentence.find("div"):
                    tmp_text = preprocess_text(sentence.get_text(" ").strip())
                    if tmp_text:
                        texts.append(tmp_text)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        reporter = soup.find("a", attrs={"class": "auth"})
        if reporter:
            reporter = reporter.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        editor = soup.find("div", attrs={"class": "editor"})
        if editor:
            editor = editor.get_text(" ").strip()
            if editor:
                editor = editor.replace("Editor :", "")
                reporters.append(editor.strip())
        return list(set(reporters))
