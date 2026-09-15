"""Sitemap monitor for discovering new articles with failure detection."""

import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from src.content_fetcher import ContentFetcher

logger = logging.getLogger(__name__)


class SitemapType(Enum):
    """Type of sitemap detected."""
    SITEMAPINDEX = "sitemapindex"  # Contains links to other sitemaps
    URLSET = "urlset"  # Contains actual article URLs
    RSS = "rss"  # RSS feed format
    UNKNOWN = "unknown"


class ScrapeStatus(Enum):
    """Status of a scrape operation."""
    SUCCESS = "success"
    PARTIAL = "partial"  # Some branches failed
    FAILED = "failed"  # Complete failure
    EMPTY = "empty"  # Scraped but no articles found


@dataclass
class ArticleMetadata:
    """Metadata for an article discovered in sitemap."""

    url: str
    headline: str
    source: str
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    published_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "headline": self.headline,
            "source": self.source,
            "category": self.category,
            "keywords": self.keywords,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


@dataclass
class BranchResult:
    """Result of scraping a single sitemap branch."""

    branch_name: str
    branch_url: str
    sitemap_type: SitemapType
    articles_found: int
    success: bool
    error: Optional[str] = None


@dataclass
class ScrapeResult:
    """Result of scraping a news source."""

    source_name: str
    status: ScrapeStatus
    total_articles: int
    branches_scraped: int
    branches_failed: int
    branch_results: List[BranchResult] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0

    def is_failed(self) -> bool:
        """Check if this scrape completely failed (0 articles)."""
        return self.status == ScrapeStatus.FAILED or self.total_articles == 0

    def get_summary(self) -> str:
        """Get a summary string for logging."""
        if self.status == ScrapeStatus.FAILED:
            return f"FAILED: {self.error or 'Unknown error'}"
        elif self.status == ScrapeStatus.EMPTY:
            return f"EMPTY: No articles found in {self.branches_scraped} branches"
        elif self.status == ScrapeStatus.PARTIAL:
            return f"PARTIAL: {self.total_articles} articles, {self.branches_failed}/{self.branches_scraped} branches failed"
        else:
            return f"SUCCESS: {self.total_articles} articles from {self.branches_scraped} branches"


@dataclass
class CrawlerConfig:
    """Configuration for a news source crawler."""

    name: str
    sitemap_url: str
    # Selectors for nested sitemaps (sitemapindex format)
    branches_selector: str = "sitemap > loc"
    # Selectors for articles (urlset format)
    article_selector: str = "url"
    title_selector: str = "news|title, news:title, title"
    link_selector: str = "loc"
    keywords_selector: str = "news|keywords, news:keywords"
    date_selector: str = "news|publication_date, news:publication_date, lastmod"
    # RSS selectors
    rss_item_selector: str = "item"
    rss_title_selector: str = "title"
    rss_link_selector: str = "link"
    rss_date_selector: str = "pubDate"
    # Options
    add_page_all: bool = True
    excluded_branches: List[str] = field(default_factory=list)
    # URL patterns to include (if empty, include all)
    include_patterns: List[str] = field(default_factory=list)


class SitemapMonitor:
    """
    Monitors news site sitemaps for new articles.
    Detects sitemap format and extracts article metadata.
    Tracks and reports failed scrapes.
    """

    def __init__(self, content_fetcher: ContentFetcher):
        """
        Initialize sitemap monitor.

        Args:
            content_fetcher: ContentFetcher instance for HTTP requests
        """
        self.fetcher = content_fetcher
        self._failed_sources: Dict[str, ScrapeResult] = {}

    def detect_sitemap_type(self, soup) -> SitemapType:
        """
        Detect the type of sitemap from its content.

        Args:
            soup: BeautifulSoup object of the sitemap

        Returns:
            SitemapType enum value
        """
        if soup is None:
            return SitemapType.UNKNOWN

        # Check for sitemapindex (contains nested sitemaps)
        if soup.find("sitemapindex") or soup.find_all("sitemap"):
            sitemaps = soup.find_all("sitemap")
            if sitemaps:
                return SitemapType.SITEMAPINDEX

        # Check for urlset (contains actual URLs)
        if soup.find("urlset") or soup.find_all("url"):
            urls = soup.find_all("url")
            if urls:
                return SitemapType.URLSET

        # Check for RSS feed
        if soup.find("rss") or soup.find("channel"):
            return SitemapType.RSS

        return SitemapType.UNKNOWN

    def get_branches(
        self, sitemap_url: str, config: CrawlerConfig
    ) -> Tuple[Dict[str, str], SitemapType]:
        """
        Get sitemap branches from main sitemap.

        Args:
            sitemap_url: Main sitemap URL
            config: Crawler configuration

        Returns:
            Tuple of (Dictionary of branch_name -> branch_url, SitemapType)
        """
        soup = self.fetcher.get_soup(sitemap_url)
        if not soup:
            logger.warning(f"Could not load sitemap from {sitemap_url}")
            return {}, SitemapType.UNKNOWN

        sitemap_type = self.detect_sitemap_type(soup)
        logger.info(f"Detected sitemap type for {config.name}: {sitemap_type.value}")

        branches = {}

        if sitemap_type == SitemapType.SITEMAPINDEX:
            # Parse nested sitemaps
            for sitemap_elem in soup.find_all("sitemap"):
                loc = sitemap_elem.find("loc")
                if loc:
                    url = loc.get_text().strip()
                    branch_name = self._extract_branch_name(url)

                    # Skip excluded branches
                    if any(excl.lower() in branch_name.lower() for excl in config.excluded_branches):
                        logger.debug(f"Skipping excluded branch: {branch_name}")
                        continue

                    branches[branch_name] = url

        elif sitemap_type == SitemapType.URLSET:
            # This is already a urlset, treat it as the only branch
            branches["main"] = sitemap_url

        elif sitemap_type == SitemapType.RSS:
            # RSS feed, treat as single branch
            branches["rss"] = sitemap_url

        # If no nested sitemaps found, treat main URL as the only branch
        if not branches:
            branches["main"] = sitemap_url

        logger.info(f"Found {len(branches)} branches for {config.name}: {list(branches.keys())}")
        return branches, sitemap_type

    def _extract_branch_name(self, url: str) -> str:
        """Extract branch name from sitemap URL."""
        # Try to extract meaningful name from URL
        patterns = [
            r"sitemap[_-]?news[_-]?([^./]+)",  # sitemap-news-ekonomi
            r"sitemap[_-]?([^./]+)",  # sitemap-ekonomi or sitemap_bisnis
            r"/([^/]+)/sitemap",  # /ekonomi/sitemap
            r"/([^/]+)-sitemap",  # /news-sitemap
            r"sitemap\.([^./]+)\.",  # sitemap.news.xml
        ]

        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                name = match.group(1).lower()
                # Filter out generic names
                if name not in ["xml", "news", "index", "www", "com", "co", "id"]:
                    return name

        # Fallback: use part of the URL path
        path_match = re.search(r"/([a-z]+)/[^/]*sitemap", url, re.IGNORECASE)
        if path_match:
            return path_match.group(1).lower()

        return "news"

    def scrape_urlset(
        self, soup, branch_name: str, config: CrawlerConfig
    ) -> List[ArticleMetadata]:
        """
        Scrape articles from a urlset sitemap.

        Args:
            soup: BeautifulSoup object
            branch_name: Name of the branch
            config: Crawler configuration

        Returns:
            List of ArticleMetadata objects
        """
        articles = []

        for url_elem in soup.find_all("url"):
            try:
                article = self._parse_urlset_article(url_elem, branch_name, config)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.debug(f"Error parsing article element: {e}")

        return articles

    def scrape_rss(
        self, soup, branch_name: str, config: CrawlerConfig
    ) -> List[ArticleMetadata]:
        """
        Scrape articles from an RSS feed.

        Args:
            soup: BeautifulSoup object
            branch_name: Name of the branch
            config: Crawler configuration

        Returns:
            List of ArticleMetadata objects
        """
        articles = []

        for item in soup.find_all(config.rss_item_selector):
            try:
                article = self._parse_rss_article(item, branch_name, config)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.debug(f"Error parsing RSS item: {e}")

        return articles

    def scrape_branch(
        self, branch_url: str, branch_name: str, config: CrawlerConfig
    ) -> BranchResult:
        """
        Scrape articles from a sitemap branch.

        Args:
            branch_url: URL of the sitemap branch
            branch_name: Name of the branch
            config: Crawler configuration

        Returns:
            BranchResult with articles and status
        """
        logger.info(f"Scraping branch '{branch_name}' from {branch_url[:60]}...")

        soup = self.fetcher.get_soup(branch_url)
        if not soup:
            return BranchResult(
                branch_name=branch_name,
                branch_url=branch_url,
                sitemap_type=SitemapType.UNKNOWN,
                articles_found=0,
                success=False,
                error="Failed to fetch sitemap",
            )

        sitemap_type = self.detect_sitemap_type(soup)
        articles = []

        if sitemap_type == SitemapType.SITEMAPINDEX:
            # This branch contains more nested sitemaps - recurse
            logger.info(f"Branch '{branch_name}' is a sitemapindex, recursing...")
            for sitemap_elem in soup.find_all("sitemap"):
                loc = sitemap_elem.find("loc")
                if loc:
                    nested_url = loc.get_text().strip()
                    nested_name = f"{branch_name}/{self._extract_branch_name(nested_url)}"
                    nested_result = self.scrape_branch(nested_url, nested_name, config)
                    # We return combined results
                    articles.extend(self._get_articles_from_result(nested_result, config))

        elif sitemap_type == SitemapType.URLSET:
            articles = self.scrape_urlset(soup, branch_name, config)

        elif sitemap_type == SitemapType.RSS:
            articles = self.scrape_rss(soup, branch_name, config)

        logger.info(f"Found {len(articles)} articles in branch '{branch_name}'")

        return BranchResult(
            branch_name=branch_name,
            branch_url=branch_url,
            sitemap_type=sitemap_type,
            articles_found=len(articles),
            success=True,
            error=None,
        )

    def _get_articles_from_result(
        self, result: BranchResult, config: CrawlerConfig
    ) -> List[ArticleMetadata]:
        """Re-fetch and parse articles from a branch result."""
        if not result.success or result.articles_found == 0:
            return []

        soup = self.fetcher.get_soup(result.branch_url)
        if not soup:
            return []

        if result.sitemap_type == SitemapType.URLSET:
            return self.scrape_urlset(soup, result.branch_name, config)
        elif result.sitemap_type == SitemapType.RSS:
            return self.scrape_rss(soup, result.branch_name, config)

        return []

    def _parse_urlset_article(
        self, url_elem, branch_name: str, config: CrawlerConfig
    ) -> Optional[ArticleMetadata]:
        """Parse a single URL element from sitemap."""
        # Get link
        loc = url_elem.find("loc")
        if not loc:
            return None

        url = loc.get_text().strip()

        # Check include patterns if specified
        if config.include_patterns:
            if not any(re.search(p, url) for p in config.include_patterns):
                return None

        # Add ?page=all if configured
        if config.add_page_all and "?page=all" not in url and "?" not in url:
            url += "?page=all"

        # Get title - try multiple selectors
        headline = None
        for selector in config.title_selector.split(","):
            selector = selector.strip()
            title_elem = url_elem.find(selector.replace("|", "\\:"))
            if title_elem:
                headline = title_elem.get_text().strip()
                break

        # Also try news:news > news:title pattern
        if not headline:
            news_elem = url_elem.find("news:news")
            if news_elem:
                title_elem = news_elem.find("news:title")
                if title_elem:
                    headline = title_elem.get_text().strip()

        if not headline:
            return None

        # Get keywords
        keywords = None
        for selector in config.keywords_selector.split(","):
            selector = selector.strip()
            keywords_elem = url_elem.find(selector.replace("|", "\\:"))
            if keywords_elem:
                keywords_text = keywords_elem.get_text().strip()
                keywords = [k.strip() for k in keywords_text.split(",") if k.strip()]
                break

        # Get publication date
        published_at = None
        for selector in config.date_selector.split(","):
            selector = selector.strip()
            date_elem = url_elem.find(selector.replace("|", "\\:"))
            if date_elem:
                published_at = self._parse_date(date_elem.get_text().strip())
                if published_at:
                    break

        # Extract category from URL or use branch name
        category = self._extract_category_from_url(url) or branch_name

        return ArticleMetadata(
            url=url,
            headline=headline,
            source=config.name,
            category=category,
            keywords=keywords,
            published_at=published_at,
        )

    def _parse_rss_article(
        self, item, branch_name: str, config: CrawlerConfig
    ) -> Optional[ArticleMetadata]:
        """Parse a single RSS item."""
        # Get link
        link_elem = item.find(config.rss_link_selector)
        if not link_elem:
            return None

        url = link_elem.get_text().strip()

        # Get title
        title_elem = item.find(config.rss_title_selector)
        headline = title_elem.get_text().strip() if title_elem else None

        if not headline:
            return None

        # Get publication date
        published_at = None
        date_elem = item.find(config.rss_date_selector)
        if date_elem:
            published_at = self._parse_date(date_elem.get_text().strip())

        # Extract category from URL or use branch name
        category = self._extract_category_from_url(url) or branch_name

        return ArticleMetadata(
            url=url,
            headline=headline,
            source=config.name,
            category=category,
            keywords=None,
            published_at=published_at,
        )

    def _parse_date(self, date_string: str) -> Optional[datetime]:
        """Parse date string to datetime."""
        from dateutil import parser

        try:
            dt = parser.parse(date_string)
            # Ensure timezone aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _extract_category_from_url(self, url: str) -> Optional[str]:
        """Extract category from article URL."""
        # Common patterns for Indonesian news sites
        patterns = [
            r"/([^/]+)/read/",  # /ekonomi/read/
            r"/([^/]+)/\d{4}/",  # /bisnis/2024/
            r"/([^/]+)/\d+/",  # /bisnis/123456/
            r"\.com/([^/]+)/",  # .com/finance/
            r"\.id/([^/]+)/",  # .id/ekonomi/
            r"\.co\.id/([^/]+)/",  # .co.id/market/
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                category = match.group(1).lower()
                # Filter out non-category segments
                if category not in ["news", "read", "detail", "artikel", "www", "amp", "m", "mobile"]:
                    return category

        return None

    def scrape_all_branches(
        self, config: CrawlerConfig
    ) -> Tuple[List[ArticleMetadata], ScrapeResult]:
        """
        Scrape all branches for a news source.

        Args:
            config: Crawler configuration

        Returns:
            Tuple of (List of ArticleMetadata, ScrapeResult)
        """
        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting full scrape for {config.name}")

        # Get branches
        branches, main_sitemap_type = self.get_branches(config.sitemap_url, config)

        if not branches:
            result = ScrapeResult(
                source_name=config.name,
                status=ScrapeStatus.FAILED,
                total_articles=0,
                branches_scraped=0,
                branches_failed=1,
                error=f"Could not load or parse sitemap from {config.sitemap_url}",
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )
            self._failed_sources[config.name] = result
            return [], result

        all_articles = []
        branch_results = []
        branches_failed = 0

        for branch_name, branch_url in branches.items():
            # Get branch result
            branch_result = self.scrape_branch(branch_url, branch_name, config)
            branch_results.append(branch_result)

            if branch_result.success:
                # Re-fetch to get actual articles
                articles = self._get_articles_from_result(branch_result, config)
                all_articles.extend(articles)
            else:
                branches_failed += 1
                logger.warning(f"Failed to scrape branch '{branch_name}': {branch_result.error}")

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        # Determine overall status
        if len(all_articles) == 0:
            if branches_failed == len(branches):
                status = ScrapeStatus.FAILED
            else:
                status = ScrapeStatus.EMPTY
        elif branches_failed > 0:
            status = ScrapeStatus.PARTIAL
        else:
            status = ScrapeStatus.SUCCESS

        result = ScrapeResult(
            source_name=config.name,
            status=status,
            total_articles=len(all_articles),
            branches_scraped=len(branches),
            branches_failed=branches_failed,
            branch_results=branch_results,
            duration_seconds=duration,
        )

        # Track failed sources
        if result.is_failed():
            self._failed_sources[config.name] = result
            logger.error(f"SCRAPE FAILED for {config.name}: {result.get_summary()}")
        else:
            # Remove from failed if it recovered
            self._failed_sources.pop(config.name, None)

        logger.info(f"Scrape result for {config.name}: {result.get_summary()}")
        return all_articles, result

    def get_failed_sources(self) -> Dict[str, ScrapeResult]:
        """
        Get all sources that failed to scrape (0 articles).

        Returns:
            Dictionary of source_name -> ScrapeResult
        """
        return self._failed_sources.copy()

    def get_failure_report(self) -> str:
        """
        Generate a failure report for all failed sources.

        Returns:
            Formatted failure report string
        """
        if not self._failed_sources:
            return "No failed sources."

        lines = [
            "=" * 60,
            "SITEMAP SCRAPE FAILURE REPORT",
            "=" * 60,
            f"Total failed sources: {len(self._failed_sources)}",
            "",
        ]

        for source_name, result in self._failed_sources.items():
            lines.append(f"Source: {source_name}")
            lines.append(f"  Status: {result.status.value}")
            lines.append(f"  Error: {result.error or 'No articles found'}")
            lines.append(f"  Branches attempted: {result.branches_scraped}")
            lines.append(f"  Branches failed: {result.branches_failed}")
            if result.branch_results:
                for br in result.branch_results:
                    status = "OK" if br.success else "FAILED"
                    lines.append(f"    - {br.branch_name}: {status} ({br.sitemap_type.value})")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def clear_failure_tracking(self):
        """Clear the failure tracking data."""
        self._failed_sources.clear()


# Predefined configurations for Indonesian news sources
CRAWLER_CONFIGS = {
    "BISNIS": CrawlerConfig(
        name="BISNIS",
        sitemap_url="https://www.bisnis.com/sitemap-news.xml",
        add_page_all=True,
    ),
    "KONTAN": CrawlerConfig(
        name="KONTAN",
        sitemap_url="https://www.kontan.co.id/sitemap.xml",
        excluded_branches=["insight", "edsus", "exportexpert"],
    ),
    "DETIK": CrawlerConfig(
        name="DETIK",
        sitemap_url="https://www.detik.com/sitemap.xml",
    ),
    "KOMPAS": CrawlerConfig(
        name="KOMPAS",
        sitemap_url="https://news.kompas.com/sitemap.xml",
    ),
    "TEMPO": CrawlerConfig(
        name="TEMPO",
        sitemap_url="https://www.tempo.co/sitemap.xml",
    ),
    "CNN": CrawlerConfig(
        name="CNN",
        sitemap_url="https://www.cnnindonesia.com/sitemap.xml",
    ),
    "CNBC": CrawlerConfig(
        name="CNBC",
        sitemap_url="https://www.cnbcindonesia.com/sitemap.xml",
    ),
    "OKEZONE": CrawlerConfig(
        name="OKEZONE",
        sitemap_url="https://news.okezone.com/sitemap.xml",
    ),
    "TRIBUN": CrawlerConfig(
        name="TRIBUN",
        sitemap_url="https://www.tribunnews.com/sitemap.xml",
    ),
    "LIPUTAN6": CrawlerConfig(
        name="LIPUTAN6",
        sitemap_url="https://www.liputan6.com/sitemap.xml",
    ),
    "MERDEKA": CrawlerConfig(
        name="MERDEKA",
        sitemap_url="https://www.merdeka.com/sitemap.xml",
    ),
    "VIVA": CrawlerConfig(
        name="VIVA",
        sitemap_url="https://www.viva.co.id/sitemap.xml",
    ),
    "TIRTO": CrawlerConfig(
        name="TIRTO",
        sitemap_url="https://tirto.id/sitemap.xml",
    ),
    "KUMPARAN": CrawlerConfig(
        name="KUMPARAN",
        sitemap_url="https://kumparan.com/sitemap.xml",
    ),
    "ANTARANEWS": CrawlerConfig(
        name="ANTARANEWS",
        sitemap_url="https://www.antaranews.com/sitemap.xml",
    ),
    "JPNN": CrawlerConfig(
        name="JPNN",
        sitemap_url="https://www.jpnn.com/sitemap.xml",
        add_page_all=False,
    ),
    "IDXCHANNEL": CrawlerConfig(
        name="IDXCHANNEL",
        sitemap_url="https://www.idxchannel.com/sitemap.xml",
    ),
    "INVESTORID": CrawlerConfig(
        name="INVESTORID",
        sitemap_url="https://investor.id/sitemap.xml",
    ),
    "WARTAEKONOMI": CrawlerConfig(
        name="WARTAEKONOMI",
        sitemap_url="https://wartaekonomi.co.id/sitemap.xml",
    ),
    "BERITASATU": CrawlerConfig(
        name="BERITASATU",
        sitemap_url="https://www.beritasatu.com/sitemap.xml",
    ),
    "SINDONEWS": CrawlerConfig(
        name="SINDONEWS",
        sitemap_url="https://www.sindonews.com/sitemap.xml",
    ),
    "MEDIAINDONESIA": CrawlerConfig(
        name="MEDIAINDONESIA",
        sitemap_url="https://mediaindonesia.com/sitemap.xml",
    ),
    "GRIDID": CrawlerConfig(
        name="GRIDID",
        sitemap_url="https://www.grid.id/sitemap.xml",
    ),
    "BATAMPOS": CrawlerConfig(
        name="BATAMPOS",
        sitemap_url="https://batampos.co.id/sitemap.xml",
    ),
    "PIKIRANRAKYAT": CrawlerConfig(
        name="PIKIRANRAKYAT",
        sitemap_url="https://www.pikiran-rakyat.com/sitemap.xml",
    ),
    "KAPANLAGI": CrawlerConfig(
        name="KAPANLAGI",
        sitemap_url="https://www.kapanlagi.com/sitemap.xml",
    ),
    "INEWS": CrawlerConfig(
        name="INEWS",
        sitemap_url="https://www.inews.id/sitemap.xml",
    ),
    "TVONENEWS": CrawlerConfig(
        name="TVONENEWS",
        sitemap_url="https://www.tvonenews.com/sitemap.xml",
    ),
    "IDNTIMES": CrawlerConfig(
        name="IDNTIMES",
        sitemap_url="https://www.idntimes.com/sitemap.xml",
    ),
    "EMITENNEWS": CrawlerConfig(
        name="EMITENNEWS",
        sitemap_url="https://www.emitennews.com/sitemap.xml",
    ),
    "ERAID": CrawlerConfig(
        name="ERAID",
        sitemap_url="https://era.id/sitemap.xml",
    ),
}
