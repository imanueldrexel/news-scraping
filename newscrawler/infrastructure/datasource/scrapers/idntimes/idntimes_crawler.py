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


class IDNTimesCrawler(Crawler):
    def __init__(self):
        super(IDNTimesCrawler, self).__init__()
        self.website_name = WebsiteName.IDNTIMES.value
        self.website_url = URL.IDNTIMES.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if link:
                    try:
                        branch_name = re.sub(r"(https://www.idntimes.com/)(\w+)(/sitemap-news.xml)", r"\2", link)
                    except BaseException:
                        branch_name = "news"
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_content = soup.find("div", attrs={"class": "article-content"})
        if article_content:
            sentences = article_content.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence and "Baca Juga: " not in sentence:
                    texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", attrs={"class": "author-name"})
        for reporter in layers:
            reporter = reporter.find("a")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporter = reporter.strip()
                    reporters.append(reporter)

        return reporters
