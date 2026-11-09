import logging
import re
from typing import Dict, List, Optional

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import preprocess_text

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SRC-41 (#135): the live index (273 entries on 2026-09-20) lists one
# `sitemap_post_<section>.xml` per section on www.jpnn.com (84 entries) and on
# each of 15 regional subdomains (bali, banten, jabar, ..., 12-21 each), next
# to `sitemap_posturl_*`/`sitemap_postimg_*` twins that are not news leaves.
_POST_LEAF = re.compile(r"^https://([a-z0-9-]+)\.jpnn\.com/sitemap_post_([^/]+)\.xml$")


class JPNNCrawler(Crawler):
    def __init__(self):
        super(JPNNCrawler, self).__init__()
        self.website_name = WebsiteName.JPNN.value
        self.website_url = URL.JPNN.value

    @staticmethod
    def branch_name_from_url(link: str) -> Optional[str]:
        """The branch key for a sitemap-index <loc>, or None when this crawler
        cannot name it: `politik` on www, `bali/politik` on a regional host --
        the host has to be part of the key or fifteen `politik` leaves collapse
        into one dict entry and fourteen regions are silently never listed.
        `/` is a boundary the SRC-35 soft-branch helper splits on. Shared with
        `scripts/fix_url_shaped_categories.py` so the stored category cannot
        drift from the live key."""
        match = _POST_LEAF.match(link.strip())
        if not match:
            return None
        host, section = match.group(1), match.group(2)
        return section if host == "www" else f"{host}/{section}"

    @classmethod
    def _get_branches(cls, soup) -> Dict[str, str]:
        # SRC-41 (#135): the old re.sub matched only the www host, so every
        # regional entry came back unchanged and became a branch keyed by
        # its own URL (78 of 90 live branches; 6,104 sitemaps.category rows).
        # Fourth instance of the SRC-14/SRC-33/SRC-36 shape: never key a
        # branch by a URL; a <loc> this crawler cannot name is skipped.
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if not loc:
                continue
            link = loc.get_text(" ").strip()
            name = cls.branch_name_from_url(link)
            if name is None:
                continue
            branches[name] = link
        return branches

    def _get_whole_text(self, soup):
        full_text = []
        while soup:
            text = self._get_text(soup)
            if text:
                full_text.extend(text)
            multiple_pages = soup.find("div", attrs={"class": ["pagination"]})
            soup = None
            if multiple_pages:
                next_page = multiple_pages.find_all("a")
                for page in next_page:
                    if page.text == "Next":
                        next_page_link = page["href"]
                        if next_page_link:
                            soup = self.page_loader.get_soup(next_page_link)

        return full_text

    @staticmethod
    def _get_text(soup):
        layer = soup.find("div", attrs={"itemprop": "articleBody"})
        if layer:
            sentences = layer.find_all("p")
            text = ""
            for sentence in sentences:
                while sentence.find_all("iframe"):
                    sentence.iframe.decompose()
                while sentence.find_all("div"):
                    sentence.div.decompose()
                while sentence.find_all("strong"):
                    sentence.strong.decompose()
                while sentence.find_all("br"):
                    sentence.br.decompose()
                tmp_text = preprocess_text(sentence.get_text(" ").strip())
                tmp_text = re.sub(r"(\s+)(\1+)", r"\1", tmp_text)
                if tmp_text not in text:
                    text += tmp_text.strip()
            return [t.strip() for t in text.split(". ")]

    def _get_reporter_from_text(self, soup) -> List[str]:
        multiple_pages = soup.find("div", attrs={"class": ["pagination"]})
        reporters = []

        if multiple_pages:
            next_page = multiple_pages.find_all("a")
            for page in next_page:
                if page.text == "Last »":
                    next_page = page["href"]
                    soup = self.page_loader.get_soup(next_page)
                    reporter = soup.find_all("p", {"class": "waktu"})
                    for r in reporter:
                        if "Redaktur & Reporter : " in r.text:
                            r = r.text.replace("Redaktur & Reporter : ", "")
                            reporters.append(r)
                        elif "Redaktur :" in r.text:
                            r = r.text.replace("Redaktur :", "")
                            r = r.replace("Reporter :", "\n")
                            r = [x.strip() for x in r.split("\n")]
                            reporters.extend(r)
        return reporters
