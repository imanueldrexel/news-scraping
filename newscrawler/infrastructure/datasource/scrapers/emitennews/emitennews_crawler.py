import logging
from typing import List, Dict

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


class EmitennewsCrawler(Crawler):
    # The sitemap index lists ~23 child sitemaps (sitemap-current-N.xml) of 1,000 URLs
    # each, newest first: child 1 covers roughly the last 3-4 weeks. A twice-daily crawl
    # only needs the first couple. Set to None to walk the whole archive (backfill).
    max_child_sitemaps = 2

    def __init__(self):
        super(EmitennewsCrawler, self).__init__()
        self.website_name = WebsiteName.EMITENNEWS.value
        self.website_url = URL.EMITENNEWS.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {"news": URL.EMITENNEWS.value}
        return branches

    def _scrape(self, branch_link, branch_name) -> List:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return articles

        child_links = [loc.get_text(" ").strip() for loc in soup.find_all("loc")]
        if self.max_child_sitemaps:
            child_links = child_links[: self.max_child_sitemaps]
        logger.info(
            f"{self.website_name}: index lists {len(soup.find_all('loc'))} child sitemaps, "
            f"reading {len(child_links)}"
        )

        for child_link in child_links:
            child_soup = self.page_loader.get_soup(child_link)
            if not child_soup:
                continue
            # Children are plain <url><loc/><lastmod/></url> entries (no news: tags).
            # Iterate the <url> parents so _get_link/_get_timestamp can find their children.
            for url in child_soup.find_all("url"):
                link = self._get_link(url)
                if not link or "/news/" not in link:
                    continue
                articles.append({
                    "link": link,
                    "headline": self._get_title(url),
                    "keywords": self._get_keywords(url),
                    "timestamp": self._get_timestamp(url, date_time_reader=self.date_time_reader),
                    "category": self._get_branch_name_from_url(link),
                    "sources": self.website_name,
                })
        return articles

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        # No <news:title> in this sitemap; derive a readable headline from the slug.
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            title = link.replace("https://www.emitennews.com/news/", "")
            title = title.replace("-", " ")
            title = title.title()
            return title

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        """Publication date from <lastmod> (date-only, e.g. 2026-09-16).

        Kept in WIB deliberately: the base class re-expresses timestamps in UTC, which
        turns a midnight-WIB date into the previous calendar day (SYS-11). Entries
        without <lastmod> return None and are dropped by _get_sitemap, instead of the
        old behaviour of stamping crawl time, which changed the dedup key every run.
        """
        lastmod = news_soup.find("lastmod")
        if not lastmod:
            return None
        raw = lastmod.get_text(" ").strip()
        if not raw:
            return None
        try:
            return date_time_reader.convert_date(raw)
        except Exception as e:
            logger.info(f"EMITENNEWS: unparseable lastmod {raw!r}: {e}")
            return None

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        read_content_layer = soup.find("div", attrs={"class": "news-page-item"})
        if read_content_layer:
            sentences = read_content_layer.find_all("p")
            texts = []
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                if sentence and "Baca juga" not in sentence:
                    texts.append(sentence)
            return texts

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
