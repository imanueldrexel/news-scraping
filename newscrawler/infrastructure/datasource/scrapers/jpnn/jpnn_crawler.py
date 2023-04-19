import logging
import re
from typing import Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import preprocess_text

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class JPNNCrawler(Crawler):
    def __init__(self):
        super(JPNNCrawler, self).__init__()
        self.website_name = WebsiteName.JPNN.value
        self.website_url = URL.JPNN.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "_post_" in link:
                    branch_name = re.sub(
                        r"(https://www.jpnn.com/sitemap_post_)(.*)(.xml)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    def _get_whole_text(self, soup):
        multiple_pages = soup.find("div", attrs={"class": ["pagination"]})
        full_text = []

        if multiple_pages:
            list_soup = [soup]
            next_page = multiple_pages.find("a", {"class": "page larger"})
            if next_page:
                next_page = next_page["href"]
                next_page_soup = self.page_loader.get_soup(next_page)
                list_soup.append(next_page_soup)
            for s in list_soup:
                text = self._get_text(s)
                full_text.extend(text)
        else:
            full_text = self._get_text(soup)

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
