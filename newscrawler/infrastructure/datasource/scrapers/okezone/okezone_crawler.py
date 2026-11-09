import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.utils.date_time_reader import DateTimeReader
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)
from newscrawler.domain.entities.extraction.website_name import WebsiteName

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OkezoneCrawler(Crawler):
    # DBT-05 (#24): this source's site selector had been dead for months (trafilatura
    # produced every saved article); trafilatura is its extractor by design.
    PRIMARY_EXTRACTOR = "trafilatura"

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

    # SRC-51 (#163): OKEZONE's sitemap generator stamps EVERY <news:publication_date>
    # (and <lastmod>) with the moment the file was rendered, not when the article
    # was published: news/nasional, 100 <url>, 1 distinct publication date, URLs
    # dated 09/22..09/24. Trusting it made `posted_at` the crawl date -- 2,299
    # stored rows had 2 distinct values -- which breaks the queue order, the RAG
    # recency weight and the newsletter's per-day clustering. Every article URL
    # carries its own date: /read/, /play/ (video) and /view/ (foto), all 2,299
    # stored links and every live branch (scripts/experiments/probe_okezone_dates.py).
    _URL_DATE_RE = re.compile(
        r"^https?://[a-z0-9-]+\.okezone\.com/(?:read|play|view)/(\d{4})/(\d{1,2})/(\d{1,2})/")
    _WIB = timezone(timedelta(hours=7))

    @classmethod
    def date_from_url(cls, link: str) -> Optional[datetime]:
        """The publication DAY from the article URL, as 00:00 WIB, or None when the
        URL carries no valid date. Only the day is stored (`posted_at` is an int
        yyyymmdd), and OKEZONE publishes no trustworthy time of day to keep."""
        match = cls._URL_DATE_RE.match((link or "").strip())
        if not match:
            return None
        try:
            return datetime(*(int(g) for g in match.groups()), tzinfo=cls._WIB)
        except ValueError:  # 2026/02/30
            return None

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        """SRC-51: the URL's date, never the sitemap's render-time stamp. A URL
        with no date returns None and the row is dropped (SYS-32's path in
        `_get_sitemap`), because the only other date on offer is known to be
        wrong."""
        loc = news_soup.find("loc")
        return OkezoneCrawler.date_from_url(loc.get_text(" ").strip()) if loc else None

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
