import collections
import logging
import os
import re
from newspaper import Article
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Dict, Optional, Union, Any, Tuple
from urllib.parse import urlparse

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER, MIN_ARTICLE_CHARS
from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NewsDetailsBatch(list):
    """What batch_crawling_details has always returned -- the NewsDetailsDTOs that
    were fetched and extracted, in order -- plus, since OPS-15, WHY each of the
    other sitemaps in the batch produced nothing: `failures` maps sitemap_id to a
    short reason ("HTTP 404", "ReadTimeout after 5 retries", "soft-404: ...", an
    exception name from the extractor). len()/iteration/indexing are unchanged
    for every existing caller; the service layer reads `failures` to store a real
    sitemaps.last_fetch_error instead of one constant string for everything.
    Same shape as SitemapSaveResult (SYS-07)."""

    def __init__(self, items=(), failures: Optional[Dict[int, str]] = None):
        super().__init__(items)
        self.failures: Dict[int, str] = dict(failures or {})


class SitemapScrapeBatch(list):
    """What batch_crawling_sitemap has always returned (a SitemapDTO per scraped
    entry) -- len()/iteration/indexing unchanged for every existing caller.
    SYS-32: additionally carries how many entries were dropped for having no
    usable publication date (neither news:publication_date nor lastmod), so
    crawl_sitemaps can log that count next to new_count instead of the drop
    being invisible. Same shape as NewsDetailsBatch/SitemapSaveResult."""

    def __init__(self, items=(), skipped_no_date: int = 0):
        super().__init__(items)
        self.skipped_no_date: int = skipped_no_date


class Crawler:
    def __init__(self):
        self.verbose = VERBOSE
        self.parallelize = PARALLELIZE
        self.date_time_reader = DateTimeReader()
        self.main_path = os.path.dirname(os.path.realpath(__file__))
        self.default_time = self.date_time_reader.convert_date("2000-01-01 00:00:01")
        self.max_worker = MAX_WORKER
        self.page_loader = RequestsPageLoader()
        self.website_url = None
        self.website_name = None

    def batch_crawling_sitemap(
        self, news: List[Dict[str, str]], website_name: str
    ) -> "SitemapScrapeBatch":
        news_data = SitemapScrapeBatch()
        if news:
            if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
                with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                    results = list(executor.map(self._get_sitemap, news))
            else:
                results = [self._get_sitemap(n) for n in news]

            # SYS-32: a lastmod-only sitemap (no news:publication_date) drops
            # here -- one summary WARNING per branch instead of one exception
            # log line per <url>. `category` on the raw dict is the branch name
            # `_scrape` stamped on every entry.
            skipped_by_branch = collections.Counter()
            for n, result in zip(news, results):
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)
                elif n.get("timestamp") is None:
                    skipped_by_branch[n.get("category") or "unknown"] += 1
            for branch, count in skipped_by_branch.items():
                logger.warning(
                    f"{website_name}/{branch}: {count} entries had no usable "
                    f"publication date (no news:publication_date or lastmod), skipped"
                )
            news_data.skipped_no_date = sum(skipped_by_branch.values())

        return news_data

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        return "news"

    def get_news_in_bulk(self) -> List:
        soup = self.page_loader.get_soup(self.website_url)
        if not soup:
            logger.warning(f"Could not load sitemap from {self.website_url}")
            return []
            
        branches_to_crawl = self._get_branches(soup)
        links_to_crawl = []
        
        for branch_name, branch_link in branches_to_crawl.items():
            links = self._scrape(branch_link=branch_link, branch_name=branch_name)
            links_to_crawl.extend(links)
        return links_to_crawl

    def _scrape(self, branch_link, branch_name) -> List:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return articles
        else:
            for idx, url in enumerate(soup.find_all("url")):
                link = self._get_link(url)
                title = self._get_title(url)
                keywords = self._get_keywords(url)
                timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                new_branch_name = self._get_branch_name_from_url(link)
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    "category": new_branch_name if branch_name == link else branch_name,
                    "sources": self.website_name,
                }
                articles.append(attributes)
            return articles

    @staticmethod
    def _get_whole_text(soup):
        pass

    @staticmethod
    def _get_sitemap(articles_data: Dict[str, Any]) -> Union[SitemapDTO, None]:
        # SYS-32: a lastmod-only leaf (TIRTO, TEMPO, BATAMPOS) has no
        # news:publication_date -- there is nothing to fall back to for a
        # sitemap row (unlike the timestamp, lastmod is not itself a
        # publication date), so drop it before it ever reaches pydantic's
        # NOT NULL-equivalent validation. batch_crawling_sitemap aggregates
        # this into one WARNING per branch instead of an exception per row.
        if articles_data.get("timestamp") is None:
            return None
        try:
            data_field_dict = {
                field: None for field in SitemapDTO.__dataclass_fields__.keys()
            }
            # sitemaps.headline is NOT NULL; a lastmod-only leaf has no
            # news:title either, so fall back to a slug derived from the URL
            # rather than lose the row -- _get_news_details prefers a real
            # page title over this placeholder when one is available.
            data_field_dict["headline"] = articles_data.get("headline") or Crawler._derive_headline_from_url(
                articles_data.get("link")
            )
            data_field_dict["keywords"] = articles_data.get("keywords")
            data_field_dict["timestamp"] = articles_data.get("timestamp")
            data_field_dict["category"] = articles_data.get("category")
            data_field_dict["link"] = articles_data.get("link")
            data_field_dict["sources"] = articles_data.get("sources")
            return SitemapDTO(**data_field_dict)
        except BaseException as e:
            logger.info(
                f"Error in get_content {articles_data.get('link')}. Reason: {e}"
            )
            return None

    @staticmethod
    def _derive_headline_from_url(link: Optional[str]) -> Optional[str]:
        """SYS-32: fallback for sitemaps.headline (NOT NULL) when the sitemap
        entry has no news:title. A news URL's slug is usually the headline in
        kebab-case ("daftar-lengkap-harga-bbm-pertamina-per-1-september-2026-hB7q"),
        so turning it into words is a serviceable placeholder -- not the real
        headline, but enough for the row to save and for the semantic filter to
        have something to score."""
        if not link:
            return None
        slug = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.(html?|xml|php)$", "", slug, flags=re.IGNORECASE)
        slug = slug.replace("-", " ").replace("_", " ").strip()
        return slug.title() if slug else None

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if not timestamp:
            # SYS-32: sitemaps.org leaves with no news: namespace (TIRTO,
            # TEMPO, BATAMPOS) carry only <lastmod>. It is not the true
            # publication date, but it is the newest signal available and the
            # only way these sources save any row at all.
            timestamp = news_soup.find("lastmod")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            # SYS-11: convert_date() already returns the correct +07:00 (WIB)
            # instant -- re-expressing it in UTC here (date_time_reader.gmt_offset)
            # shifted an article's stored calendar day backwards whenever it was
            # published 00:00-06:59 WIB, since every downstream posted_at is
            # int(dt.strftime("%Y%m%d")) on whatever tzinfo this method hands back.
            # Return the WIB instant unchanged, matching what emitennews_crawler.py
            # and antara_news_crawler.py's own _get_timestamp overrides already do
            # (the latter independently avoiding this exact bug, the former with an
            # explicit comment about it).
            return date_time_reader.convert_date(timestamp_string)

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        title = news_soup.find(news_title_element_name)
        if title:
            title = title.get_text(" ").strip()
            return title

    def _get_link(self, news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            if "?page=all" not in link and self.website_name != "JPNN":
                link += "?page=all"
            return link

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            # SYS-22 (#43): <news:keywords> is a comma-separated list per the
            # Google News sitemap spec, and every outlet emits it that way. A
            # whitespace split turned "Badan Gizi Nasional (BGN), Makan Bergizi
            # Gratis (MBG)" into eight word tokens with commas glued on, which
            # destroyed every multi-word entity the column exists to carry.
            keywords = [x.strip() for x in keywords.split(",") if x.strip()]
            return keywords

    def batch_crawling_details(
        self, news: List[SitemapDTO], website_name: str
    ) -> "NewsDetailsBatch":
        news_data = NewsDetailsBatch()
        if news:
            if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
                with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                    results = list(executor.map(self._fetch_news_details, news))
            else:
                results = [self._fetch_news_details(n) for n in news]

            for sitemap, (result, reason) in zip(news, results):
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)
                else:
                    news_data.failures[sitemap.sitemap_id] = reason or "fetch or extraction produced no result"

        return news_data

    def _get_news_details(self, sitemap: SitemapDTO) -> NewsDetailsDTO:
        return self._fetch_news_details(sitemap)[0]

    def _load_page(self, url: str):
        """(soup, reason) from the page loader. A real PageLoader reports why a fetch
        failed (OPS-15); anything else assigned to page_loader -- an object that only
        implements get_soup, including every test double -- gets the generic reason."""
        if isinstance(self.page_loader, PageLoader):
            return self.page_loader.get_soup_with_reason(url)
        soup = self.page_loader.get_soup(url)
        return (soup, None) if soup else (None, "page loader returned no document")

    def _fetch_news_details(self, sitemap: SitemapDTO) -> Tuple[Optional[NewsDetailsDTO], Optional[str]]:
        """(dto, None) on success; (None, reason) when the page could not be fetched
        or anything in the extraction path raised. OPS-15: the reason is what the
        service layer stores in sitemaps.last_fetch_error, so it must say what
        actually happened (HTTP status, timeout, soft-404, exception type) -- the
        log line alone was never queryable."""
        try:
            url = sitemap.link
            if self.website_name == "JPNN":
                url = sitemap.link.replace("?page=all", "")
            soup, fetch_reason = self._load_page(url)
            if soup is None:
                return None, fetch_reason or "page loader returned no document"
            if soup:
                # Site extractors are hand-written selectors that raise (typically
                # AttributeError on a missing container) when the layout drifts. A crash
                # must count as "extractor failed", not discard the article, so the
                # fallback chain still runs and the sitemap still gets marked attempted.
                try:
                    reporter = self._get_reporter_from_text(soup)
                    # SRC-10 (#65): a hand-written selector can drift onto a
                    # timestamp/id element instead of the byline (IDXCHANNEL's
                    # matched the publication day, storing writer=["16"] on every
                    # row) and still return a non-empty, plausible-looking string --
                    # no "missing byline" check can catch that. Drop any candidate
                    # that is purely digits or parses as a date, across every
                    # crawler, not just the one caught so far.
                    reporter = [r for r in reporter if self._looks_like_a_name(r)]
                except Exception as r_err:
                    logger.warning(f"Reporter extraction raised for {url}: {r_err!r}")
                    reporter = []
                try:
                    extracted_text = self._get_whole_text(soup)
                except Exception as x_err:
                    logger.warning(f"Site extractor raised for {url}: {x_err!r}")
                    extracted_text = None

                # Site extractors return None when their container is missing and [] when
                # it exists but no paragraph matched (layout drift). Both, and anything
                # shorter than MIN_ARTICLE_CHARS, must fall through to the next extractor.
                # OPS-02: track which extractor's output actually won, so "OK" in
                # check_crawlers.py can be told apart from "the site selector is dead
                # and a fallback is quietly doing all the work".
                extractor_used = "site"

                if not self._has_usable_text(extracted_text):
                    logger.info(f"Standard extraction failed for {url}. Attempting Trafilatura fallback...")
                    trafilatura_text = self._trafilatura_fallback(soup)
                    combined = self._best_of(extracted_text, trafilatura_text)
                    if trafilatura_text is not None and combined is trafilatura_text:
                        extractor_used = "trafilatura"
                    extracted_text = combined

                if not self._has_usable_text(extracted_text):
                    newspaper_text = self._newspaper_fallback(url)
                    combined = self._best_of(extracted_text, newspaper_text)
                    if newspaper_text is not None and combined is newspaper_text:
                        extractor_used = "newspaper"
                    extracted_text = combined

                if not self._has_usable_text(extracted_text):
                    logger.warning(
                        f"All extractors returned empty or too-short text for {url} "
                        f"({self._text_length(extracted_text)} chars)"
                    )
                    extractor_used = None

                # The DTO requires a list. Leaving None here made the DTO fail validation,
                # which returned None from this method and left the sitemap unmarked --
                # the retry-forever loop SYS-02 was meant to close.
                if extracted_text is None:
                    extracted_text = []
                elif isinstance(extracted_text, str):
                    extracted_text = [extracted_text] if extracted_text.strip() else []

                # SYS-33 (#114): a lastmod-only leaf (TIRTO, TEMPO) never has a
                # news:title, so _get_sitemap stored the URL slug as the
                # headline -- trailing id included ("... Ini Pergerakannya
                # Hca5"). SYS-32 wired _get_page_title behind
                # `sitemap.headline or ...`, which its own fallback made
                # unreachable on the live path: 317 articles kept the slug as
                # their permanent title (filter input, FAISS metadata, UI).
                # Now the page's og:title wins whenever the stored headline is
                # that placeholder (or empty); the service writes it back to
                # sitemaps.headline (`headline_from_page`), rejected rows too.
                title = sitemap.headline
                headline_from_page = False
                if not title or self._is_placeholder_headline(sitemap):
                    page_title = self._get_page_title(soup)
                    if page_title:
                        title = page_title
                        headline_from_page = True
                meta_data = {
                    "title": title,
                    "posted_at": sitemap.timestamp,
                    "extractor": extractor_used,
                    "headline_from_page": headline_from_page,
                }
                return NewsDetailsDTO(
                    sitemap_id=sitemap.sitemap_id,
                    extracted_text=extracted_text,
                    reporter=reporter,
                    meta_data=meta_data,
                ), None
            # A BeautifulSoup with no content is falsy; nothing to extract from.
            return None, "empty document"
        except BaseException as e:
            logger.info(f"Error in get_content {sitemap.link}. Reason: {e}")
            return None, f"{type(e).__name__}: {e}"[:200]

    @staticmethod
    def _slug_has_id_tail(link: str) -> bool:
        """The slug of a lastmod-only outlet's URL ends in an article id --
        TIRTO "-hCa5"/"-hCth" (4 chars, mixed case), TEMPO "-2287141" (digits).
        A real slug is lowercase words, so a last token with a digit or an
        upper-case letter is an id; a bare year ("-pilkada-2024") is not."""
        slug = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.(html?|xml|php)$", "", slug, flags=re.IGNORECASE)
        tail = slug.rsplit("-", 1)[-1] if "-" in slug else ""
        if not tail or re.fullmatch(r"(19|20)\d{2}", tail):
            return False
        return bool(re.search(r"\d", tail) or re.search(r"[A-Z]", tail))

    @classmethod
    def _is_placeholder_headline(cls, sitemap: SitemapDTO) -> bool:
        """SYS-33: True when the stored headline is what _derive_headline_from_url
        made of the link -- i.e. it came from the SYS-32 slug fallback, not from
        a news:title. Detected rather than carried as a flag so a DTO rebuilt
        from a DB row (the live full_text path loads sitemaps back from
        Postgres) is recognised too.

        Equality alone is not enough: 3,580 genuine headlines on MEDIAINDONESIA,
        JPNN, INEWS, KOMPAS, ... are short, punctuation-free Title Case and
        coincide with their own slug ("Keadilan Terkubur Longsor"). The
        placeholder additionally carries the URL's trailing id token, which a
        real headline does not, so both conditions are required."""
        if not sitemap.headline or not sitemap.link:
            return False
        if sitemap.headline != cls._derive_headline_from_url(sitemap.link):
            return False
        return cls._slug_has_id_tail(sitemap.link)

    @staticmethod
    def _get_page_title(soup) -> Optional[str]:
        """SYS-32/SYS-33: headline source when sitemap.headline is empty or a
        URL-slug placeholder -- og:title first (more curated than the raw
        <title> tag, which often carries a " | SiteName" suffix), then <title>
        itself."""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(" ").strip()
        return None

    @staticmethod
    def _text_length(extracted_text) -> int:
        """Total characters in an extraction result (None, str, or list of paragraphs)."""
        if not extracted_text:
            return 0
        if isinstance(extracted_text, str):
            return len(extracted_text.strip())
        return sum(len(p.strip()) for p in extracted_text if p)

    @classmethod
    def _has_usable_text(cls, extracted_text) -> bool:
        length = cls._text_length(extracted_text)
        return length > 0 and length >= MIN_ARTICLE_CHARS

    @classmethod
    def _best_of(cls, current, candidate):
        """Keep whichever extraction result has more text, so a failed fallback never
        replaces a short-but-real result with nothing."""
        return candidate if cls._text_length(candidate) > cls._text_length(current) else current

    @staticmethod
    def _trafilatura_fallback(soup) -> Union[List[str], None]:
        try:
            import trafilatura
            text = trafilatura.extract(str(soup))
        except Exception as t_err:
            logger.warning(f"Trafilatura fallback failed: {t_err}")
            return None
        if not text:
            return None
        logger.info("Trafilatura extraction successful.")
        # Split into paragraphs to match the shape site extractors return.
        return text.split("\n\n")

    @staticmethod
    def _newspaper_fallback(url) -> Union[List[str], None]:
        try:
            article = Article(url)
            article.download()
            article.parse()
        except Exception as n_err:
            logger.warning(f"Newspaper fallback failed: {n_err}")
            return None
        return article.text.split("\n\n") if article.text else None

    @abstractmethod
    def _get_reporter_from_text(self, soup) -> List[str]:
        pass

    @staticmethod
    def _looks_like_a_name(candidate: str) -> bool:
        """SRC-10 (#65): a reporter candidate that is purely digits or parses as a
        date is not a name -- it's a selector that landed on a timestamp or an id.
        A shared guard here catches this class of bug for every crawler's
        _get_reporter_from_text, not just the one instance already found."""
        if not candidate or not candidate.strip():
            return False
        stripped = candidate.strip()
        if re.match(r"^\d+$", stripped):
            return False
        # Date-shaped strings: "16/09/2026 17:54 WIB", "2026-09-16", "16.09.2026".
        if re.match(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", stripped):
            return False
        return True
