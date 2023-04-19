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
    def __init__(self):
        super(MediaIndonesiaCrawler, self).__init__()
        self.website_name = WebsiteName.MEDIAINDONESIA.value
        self.website_url = URL.MEDIAINDONESIA.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap_news" in link:
                    branches["news"] = link.strip()
        return branches

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        branch_name = re.sub(r"(https://www.mediaindonesia.com/)(.*)(/)", r"\1", url)
        if branch_name:
            return branch_name.strip()

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article_layer = soup.find("div", {"class": "rows jap"})
        if article_layer:
            sentences = article_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text())
                texts.append(sentence)
            return texts
