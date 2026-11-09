"""Relevance checker for filtering articles by topic."""

import logging
import re
from typing import Tuple, List, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


class RelevanceChecker:
    """
    Checks if articles are relevant to financial/economic topics.
    Uses keyword matching with optional semantic similarity.
    """

    # Default Indonesian keywords for financial/economic news
    DEFAULT_KEYWORDS = [
        # Stock market
        "pasar saham",
        "bursa efek",
        "IHSG",
        "IDX",
        "saham",
        "emiten",
        "IPO",
        "right issue",
        "dividen",
        "stock split",
        # Finance
        "keuangan",
        "perbankan",
        "bank",
        "kredit",
        "pinjaman",
        "bunga",
        "suku bunga",
        "BI rate",
        # Economy
        "ekonomi",
        "makroekonomi",
        "mikroekonomi",
        "PDB",
        "GDP",
        "inflasi",
        "deflasi",
        "resesi",
        "pertumbuhan ekonomi",
        # Investment
        "investasi",
        "investor",
        "portofolio",
        "reksadana",
        "obligasi",
        "SBN",
        "sukuk",
        # Business
        "bisnis",
        "perusahaan",
        "korporasi",
        "merger",
        "akuisisi",
        "ekspansi",
        "laporan keuangan",
        "laba",
        "rugi",
        "pendapatan",
        "revenue",
        # Commodities
        "komoditas",
        "minyak",
        "emas",
        "batu bara",
        "sawit",
        "CPO",
        "nikel",
        # Currency
        "rupiah",
        "kurs",
        "forex",
        "valuta asing",
        "dolar",
        # Trade
        "ekspor",
        "impor",
        "neraca dagang",
        "defisit",
        "surplus",
        # Government/Policy
        "kebijakan moneter",
        "fiskal",
        "APBN",
        "pajak",
        "insentif",
        "subsidi",
        # Organizations
        "Bank Indonesia",
        "OJK",
        "Kementerian Keuangan",
        "BEI",
        "KSEI",
        "Sri Mulyani",
        "Perry Warjiyo",
    ]

    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        threshold: float = 0.35,
        use_semantic: bool = False,
    ):
        """
        Initialize relevance checker.

        Args:
            keywords: List of keywords to match
            threshold: Relevance threshold (0-1)
            use_semantic: Whether to use semantic similarity
        """
        self.keywords = keywords or self.DEFAULT_KEYWORDS
        self.threshold = threshold
        self.use_semantic = use_semantic

        # Compile keyword patterns for faster matching
        self._compile_patterns()

        # Lazy load semantic model if needed
        self._semantic_model = None

    def _compile_patterns(self):
        """Compile keyword patterns for regex matching."""
        # Escape special regex characters and create word boundary patterns
        patterns = []
        for kw in self.keywords:
            escaped = re.escape(kw.lower())
            patterns.append(escaped)

        self.keyword_pattern = re.compile(
            r"\b(" + "|".join(patterns) + r")\b",
            re.IGNORECASE,
        )

    @property
    def semantic_model(self):
        """Lazy load semantic model."""
        if self._semantic_model is None and self.use_semantic:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading semantic model...")
                self._semantic_model = SentenceTransformer(
                    "paraphrase-multilingual-MiniLM-L12-v2"
                )
                logger.info("Semantic model loaded")
            except ImportError:
                logger.warning("sentence-transformers not installed")
                self.use_semantic = False
            except Exception as e:
                logger.warning(f"Failed to load semantic model: {e}")
                self.use_semantic = False

        return self._semantic_model

    def check_relevance(self, text: str) -> Tuple[bool, float]:
        """
        Check if text is relevant to financial/economic topics.

        Args:
            text: Article text to check

        Returns:
            Tuple of (is_relevant, score)
        """
        if not text:
            return False, 0.0

        # Keyword matching
        keyword_score = self._keyword_score(text)

        # Semantic matching (if enabled)
        semantic_score = 0.0
        if self.use_semantic and keyword_score < self.threshold:
            semantic_score = self._semantic_score(text)

        # Combined score
        final_score = max(keyword_score, semantic_score)

        return final_score >= self.threshold, final_score

    def _keyword_score(self, text: str) -> float:
        """
        Calculate keyword matching score.

        Args:
            text: Text to check

        Returns:
            Score between 0 and 1
        """
        # Check first portion of text (more efficient)
        check_text = text[:3000].lower()

        # Find all keyword matches
        matches = self.keyword_pattern.findall(check_text)

        if not matches:
            return 0.0

        # Count unique matches
        unique_matches = set(m.lower() for m in matches)

        # Score based on number of unique matches
        # 1 match = 0.2, 2 matches = 0.4, 3+ matches = 0.6+
        score = min(len(unique_matches) * 0.2, 1.0)

        return score

    def _semantic_score(self, text: str) -> float:
        """
        Calculate semantic similarity score.

        Args:
            text: Text to check

        Returns:
            Score between 0 and 1
        """
        if not self.semantic_model:
            return 0.0

        try:
            # Create reference text from keywords
            reference = " ".join(self.keywords[:20])

            # Use summary of article
            article_text = text[:500]

            # Compute embeddings
            embeddings = self.semantic_model.encode(
                [reference, article_text],
                convert_to_tensor=True,
            )

            # Cosine similarity
            from torch.nn.functional import cosine_similarity

            similarity = cosine_similarity(
                embeddings[0].unsqueeze(0),
                embeddings[1].unsqueeze(0),
            ).item()

            return max(0.0, similarity)

        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
            return 0.0

    def get_matched_keywords(self, text: str) -> List[str]:
        """
        Get list of matched keywords in text.

        Args:
            text: Text to check

        Returns:
            List of matched keywords
        """
        check_text = text[:3000].lower()
        matches = self.keyword_pattern.findall(check_text)
        return list(set(m.lower() for m in matches))
