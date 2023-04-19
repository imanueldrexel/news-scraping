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


class IdxChannelCrawler(Crawler):
    def __init__(self):
        super(IdxChannelCrawler, self).__init__()
        self.website_name = WebsiteName.IDXCHANNEL.value
        self.website_url = URL.IDXCHANNEL.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if link:
                    branch_name = re.sub(
                        r"(https://www.idxchannel.com/)(.*)(/sitemap.xml)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article = soup.find("div", {"class": "content"})
        if article:
            texts = []
            sentences = article.find_all("p")
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                texts.append(sentence)
            return texts
