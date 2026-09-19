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
        # SRC-14 (#92): the real index has ~63 entries, most of them
        # <section>/sitemap-web.xml or <section>/sitemap-image.xml (one with
        # 1,000 <url>, lastmod only, no news: tags). re.sub on a non-matching
        # link returned the link unchanged, so every one of those became a
        # branch keyed by its own full URL -- skip anything that doesn't match
        # the /sitemap-news.xml pattern instead of re.sub-ing it regardless.
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if not link:
                continue
            link = link.get_text(" ").strip()
            match = re.match(r"https://www\.idntimes\.com/(\w+)/sitemap-news\.xml$", link)
            if match:
                branches[match.group(1)] = link
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
