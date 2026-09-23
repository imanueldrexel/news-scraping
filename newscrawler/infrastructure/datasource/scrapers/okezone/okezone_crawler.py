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


class OkezoneCrawler(Crawler):
    def __init__(self):
        super(OkezoneCrawler, self).__init__()
        self.website_name = WebsiteName.OKEZONE.value
        self.website_url = URL.OKEZONE.value

    # SRC-43 (#146): OKEZONE publishes one sitemap per <subdomain>/<section>.
    # The old re.sub kept only the subdomain (`news`, `women`, `celebrity`), so
    # (a) every section under a subdomain collapsed onto one key and all but the
    # last were silently never crawled -- `news.okezone.com/nasional`,
    # `/megapolitan`, `/international`, `/nusantara` and nine regional desks all
    # became the single key `news` -- and (b) `sitemap-web.xml` did not match the
    # pattern at all, so 23 branches were keyed by their URL and `is_soft_branch`
    # could never see `women/beauty` or `celebrity/hotgossip` (SRC-35 #128).
    # Measured live 2026-09-23: 72 <loc> -> 34 keys (11 named). Host+path naming
    # gives 49 distinct sections, none keyed by a URL.
    #
    # Only `sitemap.xml` is listed: every section publishes both, and
    # `sitemap-web.xml` is the same URLs WITHOUT news:title/news:publication_date
    # (verified on news/nasional -- 100 urls, news:title absent), i.e. the
    # lastmod-only duplicate SYS-32 exists to drop. 49 sections, 0 web-only, so
    # nothing is lost by skipping them. Same shape as DETIK's sitemap_news filter.
    _BRANCH_RE = re.compile(r"https?://([a-z0-9-]+)\.okezone\.com/(?:([a-z0-9-]+)/)?sitemap\.xml$")

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        for sitemap in soup.find_all("sitemap"):
            link = sitemap.find("loc")
            if not link:
                continue
            link = link.get_text(" ").strip()
            match = OkezoneCrawler._BRANCH_RE.match(link)
            if not match:
                # SRC-39: a <loc> this crawler cannot name is skipped, never
                # keyed by its URL -- re.match + skip, not re.sub.
                continue
            host, section = match.group(1), match.group(2)
            branches["%s/%s" % (host, section) if section else host] = link

        return branches

    def _get_whole_text(self, soup) -> List[str]:
        texts = []
        while soup:
            text_first_page = self._get_text(soup)
            if text_first_page:
                texts.extend(text_first_page)
            next_button_soup = soup.find("div", attrs={"class": "next"})
            if next_button_soup:
                next_page_link = next_button_soup.find("a")

                current_page = soup.find("div", attrs={"class": "first-paging"})
                current_page = (
                    int(current_page.get_text(" "))
                    if current_page and int(current_page.get_text(" "))
                    else 1
                )
                max_page = soup.find("div", attrs={"class": "second-paging"})
                max_page = (
                    int(max_page.get_text(" ")) if int(max_page.get_text(" ")) else 1
                )
                if next_page_link and (max_page / current_page) != 1:
                    next_page_link = next_page_link["href"]
                    soup = self.page_loader.get_soup(next_page_link)
                else:
                    break
        return texts

    @staticmethod
    def _get_text(soup) -> List[str]:
        soup = soup.find("div", attrs={"class": "detail detail__billboard class-vidy"})
        layer = soup.find(
            "div", attrs={"itemprop": "articleBody", "class": "read", "id": "contentx"}
        )
        if layer:
            sentences = layer.find_all("p")
            texts = []
            for sentence in sentences[:1]:
                divs = sentence.find_all("div")
                for div in divs:

                    if div.attrs == {"class": ["first-paging"]} or div.attrs == {
                        "class": ["second-paging"]
                    }:

                        continue
                    else:
                        div.decompose()
                divs = sentence.find_all("div")

                if sentence.attrs != {}:
                    continue
                extracted_text = preprocess_text(sentence.text.strip())
                if len(extracted_text) > 0:
                    texts.append(extracted_text)

            return texts

        # read_content_layer = soup.find("div", attrs={"class": "read__content"})
        # if not read_content_layer:
        #     read_content_layer = soup.find(
        #         "div", attrs={"class": "side-article txt-article"}
        #     )
        # if read_content_layer:
        #     sentences = read_content_layer.find_all("p")
        #     texts = []
        #     for sentence in sentences:
        #         sentence = preprocess_text(sentence.get_text(" ").strip())
        #         if sentence and "Baca juga" not in sentence:
        #             texts.append(sentence)
        #     return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layers = soup.find_all("div", attrs={"class": "read__credit__item"})
        for reporter in layers:
            reporter = reporter.find("a")
            if reporter:
                reporter = reporter.get_text(" ")
                if reporter:
                    reporter = reporter.strip()
                    reporters.append(reporter)

        return reporters
