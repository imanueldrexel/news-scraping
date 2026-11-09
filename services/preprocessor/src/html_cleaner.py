"""HTML cleaner for extracting clean text from articles."""

import re
import logging
from typing import Tuple, Optional, List
from bs4 import BeautifulSoup
import trafilatura

logger = logging.getLogger(__name__)


class HTMLCleaner:
    """
    Extracts and cleans text from HTML content.
    Uses trafilatura with BeautifulSoup fallback.
    """

    # Indonesian boilerplate patterns to remove
    BOILERPLATE_PATTERNS = [
        r"Baca\s+[Jj]uga\s*[:.]?",
        r"Lihat\s+[Jj]uga\s*[:.]?",
        r"Simak\s+berita\s+lainnya",
        r"Bergabung\s+dan\s+dapatkan",
        r"Dapatkan\s+update\s+berita",
        r"Cek\s+berita\s+dan\s+artikel",
        r"Yuk,\s+baca\s+artikel",
        r"Tonton\s+juga\s+video",
        r"Selengkapnya\s+di\s+sini",
        r"Klik\s+untuk\s+membaca",
        r"ADVERTISEMENT",
        r"SCROLL\s+TO\s+CONTINUE",
        r"\[.*?\]",  # Remove bracketed content like [Gambas:Video]
    ]

    # Author/reporter patterns
    AUTHOR_PATTERNS = [
        r"^(?:Reporter|Penulis|Editor|Kontributor)\s*[:]\s*(.+?)$",
        r"^Oleh\s*[:]\s*(.+?)$",
        r"^(?:Ditulis|Dilaporkan)\s+oleh\s*[:]\s*(.+?)$",
    ]

    # Common ad/noise selectors to remove
    NOISE_SELECTORS = [
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "aside",
        ".advertisement",
        ".ads",
        ".social-share",
        ".related-articles",
        ".comments",
        "#comments",
        ".sidebar",
        ".author-box",
        ".share-buttons",
    ]

    def __init__(self):
        self.boilerplate_regex = re.compile(
            "|".join(self.BOILERPLATE_PATTERNS), re.IGNORECASE | re.MULTILINE
        )

    def clean(self, html: str, source: str = "") -> Tuple[str, Optional[List[str]]]:
        """
        Extract clean text and reporter from HTML.

        Args:
            html: Raw HTML content
            source: News source name for source-specific handling

        Returns:
            Tuple of (clean_text, reporter_list)
        """
        if not html:
            return "", None

        # Try trafilatura first (best for news articles)
        text = self._extract_with_trafilatura(html)

        # Fallback to BeautifulSoup
        if not text or len(text) < 100:
            text = self._extract_with_beautifulsoup(html)

        if not text:
            return "", None

        # Extract reporter before cleaning
        reporter = self._extract_reporter(html)

        # Clean the text
        text = self._remove_boilerplate(text)
        text = self._normalize_whitespace(text)

        return text.strip(), reporter

    def _extract_with_trafilatura(self, html: str) -> Optional[str]:
        """Extract text using trafilatura."""
        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            return text
        except Exception as e:
            logger.debug(f"Trafilatura extraction failed: {e}")
            return None

    def _extract_with_beautifulsoup(self, html: str) -> Optional[str]:
        """Extract text using BeautifulSoup."""
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Remove noise elements
            for selector in self.NOISE_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()

            # Try to find article body
            article_selectors = [
                "article",
                '[itemprop="articleBody"]',
                ".article-content",
                ".article-body",
                ".post-content",
                ".entry-content",
                ".content-artikel",
                ".detail-content",
                "#article-content",
            ]

            article = None
            for selector in article_selectors:
                article = soup.select_one(selector)
                if article:
                    break

            if not article:
                # Fall back to body
                article = soup.body if soup.body else soup

            # Extract paragraphs
            paragraphs = []
            for p in article.find_all(["p", "div.paragraph"]):
                text = p.get_text(separator=" ", strip=True)
                if text and len(text) > 20:
                    paragraphs.append(text)

            return "\n\n".join(paragraphs)

        except Exception as e:
            logger.debug(f"BeautifulSoup extraction failed: {e}")
            return None

    def _extract_reporter(self, html: str) -> Optional[List[str]]:
        """Extract reporter/author names from HTML."""
        try:
            soup = BeautifulSoup(html, "html.parser")

            reporters = []

            # Try meta author tag
            meta_author = soup.find("meta", {"name": "author"})
            if meta_author and meta_author.get("content"):
                reporters.append(meta_author["content"])

            # Try common author selectors
            author_selectors = [
                ".author-name",
                ".reporter-name",
                '[rel="author"]',
                ".writer",
                ".penulis",
                ".kontributor",
                '[itemprop="author"]',
            ]

            for selector in author_selectors:
                elements = soup.select(selector)
                for elem in elements:
                    name = elem.get_text(strip=True)
                    if name and name not in reporters:
                        reporters.append(name)

            # Try regex patterns in text
            text = soup.get_text()
            for pattern in self.AUTHOR_PATTERNS:
                matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
                for match in matches:
                    name = match.strip()
                    if name and name not in reporters:
                        reporters.append(name)

            return reporters if reporters else None

        except Exception as e:
            logger.debug(f"Reporter extraction failed: {e}")
            return None

    def _remove_boilerplate(self, text: str) -> str:
        """Remove boilerplate text patterns."""
        # Remove boilerplate patterns
        text = self.boilerplate_regex.sub("", text)

        # Remove lines that are too short (likely navigation)
        lines = text.split("\n")
        lines = [line for line in lines if len(line.strip()) > 30 or not line.strip()]

        return "\n".join(lines)

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace in text."""
        # Replace multiple newlines with double newline
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Replace multiple spaces with single space
        text = re.sub(r"[ \t]+", " ", text)

        # Remove leading/trailing whitespace from lines
        lines = [line.strip() for line in text.split("\n")]

        return "\n".join(lines)

    def get_summary(self, text: str, max_sentences: int = 3) -> str:
        """
        Get first few sentences as summary.

        Args:
            text: Full article text
            max_sentences: Maximum number of sentences

        Returns:
            Summary text
        """
        if not text:
            return ""

        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)

        # Take first N sentences
        summary_sentences = sentences[:max_sentences]

        return " ".join(summary_sentences)
