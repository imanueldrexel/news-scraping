"""DBT-29 (#107): classify_batch predated SYS-31's category deny-list --
_FETCH_SQL didn't even select sitemaps.category, so a row like headline
"Rupiah Menguat" under category="hiburan" (which the live filter now hard-
rejects via is_offtopic_category, before ever scoring the text) was left
'pending' forever because the bare headline cleared the raw threshold.

SYS-35 (#118): the gate is symmetric. A news-desk category (`ekonomi`,
`nasional`) keeps the row pending without scoring -- this script used to do
exactly what the live filter did before SYS-35 and permanently rejected
finance-section rows whose bare headline scored under 0.35. Both gates come
from the one `category_gate` the live filter uses, never a local copy.
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


def _scores(*values):
    return MagicMock(max=lambda dim: MagicMock(values=list(values)))


class TestClassifyBatchCategoryGate(unittest.TestCase):
    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_offtopic_category_rejected_regardless_of_headline_score(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = _scores(0.99)

        important = classify_batch(filt, ["Rupiah Menguat Terhadap Dolar AS"], ["hiburan"])

        self.assertEqual(important, [False])
        filt.model.encode.assert_not_called()

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_finance_category_kept_pending_without_scoring(self, cos_sim):
        # SYS-35: a finance section is news by the publisher's own filing; a
        # low headline score (world oil prices: 0.254) must not reject it.
        filt = _make_filter()
        cos_sim.return_value = _scores(0.10)

        important = classify_batch(filt, ["Harga Minyak Dunia Turun Usai AS Ungkap Pipa Arab Saudi"], ["ekonomi"])

        self.assertEqual(important, [True])
        filt.model.encode.assert_not_called()

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_hard_news_category_kept_pending_without_scoring(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = _scores(0.10)
        important = classify_batch(filt, ["Prabowo Puji PDIP di Luar Pemerintah"], ["politik-dan-hukum"])
        self.assertEqual(important, [True])
        filt.model.encode.assert_not_called()

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_mixed_bucket_is_scored(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = _scores(0.20, 0.80)
        important = classify_batch(filt, ["Kekalahan untuk Refleksi Diri", "Rupiah Menguat"], ["news", "news"])
        self.assertEqual(important, [False, True])
        self.assertEqual(filt.model.encode.call_args[0][0], ["Kekalahan untuk Refleksi Diri", "Rupiah Menguat"])

    @patch("scripts.backfill_sitemap_crawl_status.util.cos_sim")
    def test_mixed_batch_only_the_mixed_bucket_row_reaches_the_model(self, cos_sim):
        filt = _make_filter()
        cos_sim.return_value = _scores(0.99)

        important = classify_batch(
            filt,
            ["Rupiah Menguat", "Ria Ricis Nangis Lihat Sapi", "Kebakaran Kemayoran Diduga Akibat Korsleting"],
            ["ekonomi", "hiburan", "news"],
        )

        self.assertEqual(important, [True, False, True])
        encoded_arg = filt.model.encode.call_args[0][0]
        self.assertEqual(encoded_arg, ["Kebakaran Kemayoran Diduga Akibat Korsleting"])

    def test_blank_headline_never_encoded_regardless_of_category(self):
        filt = _make_filter()
        important = classify_batch(filt, ["", "   "], ["ekonomi", "news"])
        self.assertEqual(important, [False, False])
        filt.model.encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
