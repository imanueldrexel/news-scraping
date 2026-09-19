import logging
import re
from typing import List, Optional
from sentence_transformers import SentenceTransformer, util

# Configure logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-31 (#86): category values that are never finance/economy on any outlet
# observed in production (scripts/experiments/probe_filter_precision.py), applied
# before the semantic score. Lifestyle/entertainment/sports/religion/travel
# verticals and GRIDID's whole magazine network score inside the model's noise
# band ([0.35, 0.45) against short INTERESTS phrases) just as often as real
# economy news -- "Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih" scores
# 0.421 vs `Rupiah`, above the corpus median -- so no threshold on the cosine
# score alone can separate them; the category is a free, reliable signal.
#
# NOTE (2026-09-20, pre-cleanup verification for SYS-31's data-deletion step):
# "otomotif" was removed from both sets below after sampling actual saved
# titles under it on WARTAEKONOMI and SINDONEWS -- both were real auto-market
# business coverage (EV subsidies, fiscal risk, car sales/market-share
# figures), not lifestyle car reviews. A bare "otomotif" category label does
# not reliably mean off-topic on this corpus; GRIDID's dedicated car-hobbyist
# magazine brands (Gridoto, Motorplus, Otomotifnet) are unambiguous and stay.
OFFTOPIC_CATEGORIES_EXACT = {
    "hiburan", "fashion", "lifestyle", "olahraga", "bola", "sport", "sports",
    "kuliner", "sajian", "travel", "wisata", "destinasi", "piknik",
    "religi", "kalam", "ramadan", "edukasi", "forum-mahasiswa", "kriminal",
    "entertainment", "gaya-hidup", "idxtainment", "ecotainment",
    "entertainment_life_style", "travelista", "sepak-bola", "jelita",
    # GRIDID: every category the source has ever saved under is a lifestyle/
    # hobby magazine brand (Grid Network), none finance.
    "gridid", "intisari", "fotokita", "idea", "nationalgeographic", "nakita",
    "nova", "infokomputer", "gridoto", "otomotifnet", "hai", "motorplus",
    "gridhealth", "nextren", "juara", "cewekbanget", "bolasport", "stylo",
}
# Substring match for category values that are not clean labels -- e.g. JPNN
# stores a raw per-region sitemap URL as `category` for many rows
# ("https://bali.jpnn.com/sitemap_post_kriminal.xml"). Most of these are
# checked as plain substrings; "sport" is checked with a word boundary
# instead (see is_offtopic_category) because "transportasi" -- Indonesian for
# "transportation", nothing to do with sports -- contains "sport" by pure
# coincidence (tran-SPORT-asi) and was a real false positive on WARTAEKONOMI
# caught by sampling actual titles before the SYS-31 cleanup delete ran.
OFFTOPIC_CATEGORY_KEYWORDS_SUBSTRING = (
    "olahraga", "kriminal", "lifestyle", "hiburan", "kuliner",
    "travel", "religi", "destinasi", "tainment",
)
OFFTOPIC_CATEGORY_KEYWORDS_WORD = (
    "sport",
)

# Short topic anchors for verticals that keep landing in the cosine noise band
# against INTERESTS even though they are not finance. Used as a contrastive
# check (SemanticImportanceFilter.margin): an article must score higher against
# INTERESTS than against these, not merely clear the raw threshold. This is the
# fallback for articles whose sitemap.category is missing, blank, or not (yet)
# covered by the deny-list above. No "Otomotif" entry, for the same reason
# it isn't a category keyword -- real auto-market business content would
# score close to it too.
OFFTOPIC_INTERESTS = [
    "Hiburan dan Gosip Selebriti", "Gaya Hidup dan Fashion", "Kuliner dan Resep Masakan",
    "Olahraga dan Sepak Bola", "Wisata dan Travel", "Agama dan Religi",
    "Kriminal dan Kecelakaan", "Politik dan Pemilu",
]


def is_offtopic_category(category: Optional[str]) -> bool:
    """SYS-31: hard deny-list applied before the semantic score, on categories
    that are never finance/economy regardless of what the article text scores."""
    if not category:
        return False
    normalized = category.strip().lower()
    if normalized in OFFTOPIC_CATEGORIES_EXACT:
        return True
    if any(keyword in normalized for keyword in OFFTOPIC_CATEGORY_KEYWORDS_SUBSTRING):
        return True
    # Plain \b treats "_" as a word character, so it would not see a boundary
    # in "post_sport" -- category/URL slugs use "_"/"-"/"." as separators just
    # as often as they use letters, so the boundary is "not alphanumeric".
    return any(
        re.search(rf"(?:^|[^a-z0-9]){keyword}s?(?:[^a-z0-9]|$)", normalized)
        for keyword in OFFTOPIC_CATEGORY_KEYWORDS_WORD
    )


class SemanticImportanceFilter:
    def __init__(self, interests: List[str], threshold: float = 0.35, model_name: str = 'all-MiniLM-L6-v2',
                 offtopic_interests: Optional[List[str]] = None, margin: float = 0.035):
        """
        Initialize the Semantic Importance Filter.

        Args:
            interests: List of strings describing the user's interests (e.g. "Artificial Intelligence", "Stock Market").
            threshold: Cosine similarity threshold (0 to 1). Articles above this are "important".
            model_name: Sentence Transformer model name.
            offtopic_interests: SYS-31 -- reference topics an article must score
                below (relative to `margin`) its best `interests` score, even if
                it clears `threshold`. Raw cosine similarity against short
                INTERESTS phrases alone does not separate finance from
                lifestyle/entertainment content in the noise band just above
                `threshold`; scoring against a contrasting off-topic set catches
                what the category deny-list (`is_offtopic_category`) misses.
            margin: how much higher the best INTERESTS score must be than the
                best off-topic score for an article to pass.
        """
        logger.info(f"Loading Semantic Filter Model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.interests = interests
        self.threshold = threshold
        self.margin = margin

        # Pre-encode interests for speed
        self.interest_embeddings = self.model.encode(self.interests, convert_to_tensor=True)

        self.offtopic_interests = offtopic_interests or []
        self.offtopic_embeddings = (
            self.model.encode(self.offtopic_interests, convert_to_tensor=True)
            if self.offtopic_interests else None
        )
        logger.info(f"Initialized Semantic Filter with interests: {self.interests}")

    def is_important(self, text: str, category: Optional[str] = None) -> bool:
        """
        Check if the text is semantically similar to any of the interests, and
        not a category or off-topic anchor known to be non-finance (SYS-31).
        """
        if not text:
            return False

        if is_offtopic_category(category):
            return False

        # Truncate text to first 200 words for speed and relevance (intros usually contain the topic)
        text_snippet = " ".join(text.split()[:200])

        # Encode the article text
        article_embedding = self.model.encode(text_snippet, convert_to_tensor=True)

        # Calculate cosine similarities
        cosine_scores = util.cos_sim(article_embedding, self.interest_embeddings)

        # Find the max similarity score
        max_score = float(cosine_scores.max())

        if max_score < self.threshold:
            return False

        if self.offtopic_embeddings is not None:
            offtopic_scores = util.cos_sim(article_embedding, self.offtopic_embeddings)
            max_offtopic = float(offtopic_scores.max())
            if max_offtopic + self.margin >= max_score:
                logger.debug(
                    f"Article scored {max_score:.3f} vs interests but {max_offtopic:.3f} "
                    f"vs off-topic anchors (margin {self.margin}) -- rejecting"
                )
                return False

        logger.debug(f"Article matched with score {max_score:.3f}")
        return True
