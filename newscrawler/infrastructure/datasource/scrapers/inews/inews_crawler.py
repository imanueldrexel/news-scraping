import logging
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.website_name import WebsiteName

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class INewsCrawler(Crawler):
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
