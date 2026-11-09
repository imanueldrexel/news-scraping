import logging
import re
from typing import Dict, List

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KontanCrawler(Crawler):
    # DBT-05 (#24): this source's site selector had been dead for months (trafilatura
    # produced every saved article); trafilatura is its extractor by design.
    PRIMARY_EXTRACTOR = "trafilatura"

    # SRC-52 (#169, owner decision 2026-09-25): no exceptions. `english` was kept
    # by SRC-35 as KONTAN's market wire ("GLOBAL MARKETS-Oil Jump Sends 30-Year
    # Yields to Two-Decade High"), but the category gate denies `english`, so the
    # exception only bought a fetch per row before a certain rejection (300 rows,
    # 0 saved). The owner chose to drop the branch rather than scope an allow.

    def __init__(self):
        super(KontanCrawler, self).__init__()
        self.website_name = WebsiteName.KONTAN.value
        self.website_url = URL.KONTAN.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            avoided_keyword = [
                "insight",
                "edsus",
                "exportexpert",
                "kilaskementerian",
                "kilaskorporasi",
                "pialaeropa",
            ]
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in link:
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if "/news/" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.kontan)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(
                            r"(https://www.kontan.co.id/)(.*)(/news/sitemap.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find(
            "div",
            attrs={
                "itemprop": ["articleBody"],
                "class": ["tmpt-desk-kon", "ctn", None],
            },
        )
        if layer:
            sentences = layer.find("p")
            if sentences:
                reporter = sentences.get_text(" ").strip()
                if reporter:
                    for r in reporter.split("|"):
                        r = r.replace("Reporter:", "")
                        r = r.replace("Editor:", "")
                        r = r.strip()
                        reporters.append(r)
                    return reporters
