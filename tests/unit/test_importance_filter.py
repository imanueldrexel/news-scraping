"""SYS-31 (#86): the category deny-list must reject known off-topic categories
without loading the embedding model, and the off-topic-anchor margin must be
wired into SemanticImportanceFilter's constructor/is_important signature."""
import unittest
from unittest.mock import MagicMock, patch

from newscrawler.core.importance_filter import (
    SemanticImportanceFilter,
    is_offtopic_category,
    OFFTOPIC_CATEGORIES_EXACT,
    OFFTOPIC_INTERESTS,
)


class TestIsOffTopicCategory(unittest.TestCase):
    def test_none_and_empty_are_not_offtopic(self):
        self.assertFalse(is_offtopic_category(None))
        self.assertFalse(is_offtopic_category(""))

    def test_known_offtopic_categories(self):
        for cat in ("hiburan", "fashion", "lifestyle", "Sajian", "Nakita", "olahraga", "religi"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_case_insensitive(self):
        self.assertTrue(is_offtopic_category("HIBURAN"))
        self.assertTrue(is_offtopic_category("GridID"))

    def test_finance_categories_are_not_offtopic(self):
        for cat in ("ekonomi", "bisnis", "market-news", "banking", "finansial", "syariah"):
            self.assertFalse(is_offtopic_category(cat), f"{cat!r} should not be off-topic")

    def test_url_shaped_jpnn_category_matched_by_keyword(self):
        self.assertTrue(is_offtopic_category("https://bali.jpnn.com/sitemap_post_kriminal.xml"))
        self.assertTrue(is_offtopic_category("https://jogja.jpnn.com/sitemap_post_olahraga.xml"))

    def test_ambiguous_regional_category_not_denied(self):
        # Regional/political categories are not in scope for this deny-list --
        # they may contain finance content and are left to the semantic score.
        self.assertFalse(is_offtopic_category("daerah"))
        self.assertFalse(is_offtopic_category("nasional"))

    def test_otomotif_is_not_denied(self):
        """2026-09-20, found while verifying the SYS-31 cleanup before it ran:
        sampled real saved titles under "otomotif" on WARTAEKONOMI and
        SINDONEWS -- both were auto-market business coverage (EV subsidies,
        car sales/market-share figures), not lifestyle reviews. A bare
        "otomotif" category is not a reliable off-topic signal on this corpus."""
        self.assertFalse(is_offtopic_category("otomotif"))
        self.assertFalse(is_offtopic_category("Otomotif"))

    def test_gridid_automotive_magazine_brands_still_denied(self):
        # Unlike a bare "otomotif" news-portal section, these are unambiguous
        # dedicated car-hobbyist magazine brands (GRIDID/Grid Network).
        for cat in ("Gridoto", "Motorplus", "Otomotifnet"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should still be off-topic")

    def test_transportasi_is_not_a_false_positive_via_the_sport_substring(self):
        """"transportasi" (Indonesian for "transportation") contains "sport"
        purely by coincidence (tran-SPORT-asi) -- a plain substring check on
        the "sport" keyword flagged real WARTAEKONOMI logistics/infrastructure
        coverage as off-topic. Must not be denied."""
        self.assertFalse(is_offtopic_category("transportasi"))

    def test_sport_keyword_still_matches_real_sport_categories(self):
        # The word-boundary fix for "sport" must still catch these.
        self.assertTrue(is_offtopic_category("bola-sports"))
        self.assertTrue(is_offtopic_category("https://bali.jpnn.com/sitemap_post_sport.xml"))
        self.assertTrue(is_offtopic_category("sport"))


class TestSemanticImportanceFilterCategoryGate(unittest.TestCase):
    """Category check must short-circuit before the model ever runs."""

    def _make_filter_without_loading_model(self):
        filt = SemanticImportanceFilter.__new__(SemanticImportanceFilter)
        filt.model = MagicMock()
        filt.interests = ["Ekonomi"]
        filt.threshold = 0.35
        filt.margin = 0.03
        filt.interest_embeddings = MagicMock()
        filt.offtopic_interests = OFFTOPIC_INTERESTS
        filt.offtopic_embeddings = MagicMock()
        return filt

    def test_offtopic_category_rejected_without_encoding(self):
        filt = self._make_filter_without_loading_model()
        result = filt.is_important("some text", category="hiburan")
        self.assertFalse(result)
        filt.model.encode.assert_not_called()

    def test_empty_text_rejected(self):
        filt = self._make_filter_without_loading_model()
        self.assertFalse(filt.is_important("", category=None))


class TestSemanticImportanceFilterMargin(unittest.TestCase):
    """Real model, real off-topic anchors: verifies the margin actually
    separates a lifestyle/celebrity text from a finance one when category is
    unavailable (category=None) -- the defense-in-depth path for sources whose
    category is missing or not yet in the deny-list."""

    @classmethod
    def setUpClass(cls):
        from newscrawler.core.constants import INTERESTS
        cls.filt = SemanticImportanceFilter(
            interests=INTERESTS,
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            offtopic_interests=OFFTOPIC_INTERESTS,
        )

    def test_celebrity_gossip_rejected_with_no_category(self):
        text = ("Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih. Selebgram itu tak kuasa "
                "menahan tangis saat sapi kesayangannya disembelih di Idul Adha.")
        self.assertFalse(self.filt.is_important(text, category=None))

    def test_real_finance_headline_still_passes(self):
        text = ("Bank Indonesia Naikkan Suku Bunga Acuan 25 Basis Poin. Rapat Dewan Gubernur BI "
                "menahan inflasi yang masih tinggi di tengah pelemahan Rupiah.")
        self.assertTrue(self.filt.is_important(text, category=None))


if __name__ == "__main__":
    unittest.main()
