import logging
import re
from typing import Dict, List

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
                        next_page_link = page['href']
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
                    next_page = page['href']
                    soup = self.page_loader.get_soup(next_page)
                    reporter = soup.find_all("p", {"class": "waktu"})
                    for r in reporter:
                        if "Redaktur & Reporter : " in r.text:
                            r = r.text.replace("Redaktur & Reporter : ", "")
                            reporters.append(r)
                        elif "Redaktur :" in r.text:
                            r = r.text.replace("Redaktur :", '')
                            r = r.replace("Reporter :", '\n')
                            r = [x.strip() for x in r.split('\n')]
                            reporters.extend(r)
        return reporters
