"""DBT-29 (#107): classify_batch predated SYS-31's category deny-list --
_FETCH_SQL didn't even select sitemaps.category, so a row like headline
"Rupiah Menguat" under category="hiburan" (which the live filter now hard-
rejects via is_offtopic_category, before ever scoring the text) was left
'pending' forever because the bare headline cleared the raw threshold.
"""
import unittest
from unittest.mock import MagicMock, patch

from scripts.backfill_sitemap_crawl_status import classify_batch


def _make_filter():
    filt = MagicMock()
    filt.threshold = 0.35
    filt.interest_embeddings = MagicMock()
    filt.model.encode.side_effect = lambda headlines, convert_to_tensor=True: list(headlines)
    return filt


class TestClassifyBatchCategoryGate(unittest.TestCase):
    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_offtopic_category_rejected_regardless_of_headline_score(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = MagicMock(max=lambda dim: MagicMock(values=[0.99]))

        important = classify_batch(filt, ["Rupiah Menguat Terhadap Dolar AS"], ["hiburan"])

        self.assertEqual(important, [False])
        filt.model.encode.assert_not_called()

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_finance_category_with_high_score_is_important(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = MagicMock(max=lambda dim: MagicMock(values=[0.99]))

        important = classify_batch(filt, ["Rupiah Menguat Terhadap Dolar AS"], ["ekonomi"])

        self.assertEqual(important, [True])
        filt.model.encode.assert_called_once()

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_mixed_batch_offtopic_row_excluded_from_encoding(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = MagicMock(max=lambda dim: MagicMock(values=[0.99]))

        important = classify_batch(
            filt,
            ["Rupiah Menguat", "Ria Ricis Nangis Lihat Sapi"],
            ["ekonomi", "hiburan"],
        )

        self.assertEqual(important, [True, False])
        # Only the non-off-topic headline should have reached the model.
        encoded_arg = filt.model.encode.call_args[0][0]
        self.assertEqual(encoded_arg, ["Rupiah Menguat"])

    def test_blank_headline_never_encoded_regardless_of_category(self):
        filt = _make_filter()
        important = classify_batch(filt, [""], ["ekonomi"])
        self.assertEqual(important, [False])
        filt.model.encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
