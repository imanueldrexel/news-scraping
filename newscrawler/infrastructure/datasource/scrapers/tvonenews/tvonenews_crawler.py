import logging
import re
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


class TVOneNewsCrawler(Crawler):
    def __init__(self):
        super(TVOneNewsCrawler, self).__init__()
        self.website_name = WebsiteName.TVONENEWS.value
        self.website_url = URL.TVONENEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "/news/" in link:
                    try:
                        branch_name = re.sub(r"(https://www.tvonenews.com/sitemap/news/)(\w+)(.*)", r"\2", link)
                        if branch_name in ["news-sitemap.xml", "berita"]:
                            branch_name = "news"
                    except BaseException :
                        branch_name = "news"
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"class": "detail-content"})
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence and "Baca juga" not in sentence:
                    texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", attrs={"class": "detail-author-data"})
        for reporter in layers:
            reporter = reporter.find("a")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter and reporter != "Tim TvOne, Tim TvOne":
                    reporter = reporter.replace("Tim TvOne, ", '')
                    reporter = reporter.strip()
                    reporters.append(reporter)

        return reporters
