"""DBT-29 (#107): classify_batch predated SYS-31's category deny-list --
_FETCH_SQL didn't even select sitemaps.category, so a row like headline
"Rupiah Menguat" under category="hiburan" (which the live filter now hard-
rejects via is_offtopic_category, before ever scoring the text) was left
'pending' forever because the bare headline cleared the raw threshold.

SYS-35 (#118) / SYS-37 (#121): the script's `classify_batch` is no longer a
copy of the live decision -- it IS the live decision:
SemanticImportanceFilter.classify_batch (DBT-31's one-decision-function
finding). What is pinned here is that the script hands the live filter every
row, in order, with its category, and maps the decisions back one-to-one; the
gate/probe behaviour itself is tested in test_importance_filter.py.
"""
import unittest
from unittest.mock import MagicMock

from newscrawler.core.importance_filter import FilterDecision
from scripts.backfill_sitemap_crawl_status import classify_batch


def _filter_returning(*decisions):
    filt = MagicMock()
    filt.classify_batch.return_value = list(decisions)
    return filt


class TestClassifyBatchUsesTheLiveFilter(unittest.TestCase):
    def test_every_row_goes_to_the_live_filter_with_its_category_in_order(self):
        filt = _filter_returning(
            FilterDecision(False, "deny"), FilterDecision(True, "allow", True, "markets", 0.9, 0.1),
            FilterDecision(False, "empty"), FilterDecision(False, "score", False, "other_news", 0.4, 0.8),
        )
        headlines = ["Rupiah Menguat Terhadap Dolar AS", "Harga Minyak Dunia Turun", "", "Doa Hari Ini"]
        categories = ["hiburan", "ekonomi", "bisnis", "news"]

        important = classify_batch(filt, headlines, categories)

        filt.classify_batch.assert_called_once_with(headlines, categories, None)
        self.assertEqual(important, [False, True, False, False])

    def test_a_news_desk_row_is_the_probes_call_not_an_automatic_keep(self):
        # SYS-45: `allow` no longer means "never reject" -- whatever the live
        # filter returns for an `ekonomi` row is what the script records.
        filt = _filter_returning(FilterDecision(False, "allow", False, "corporate", 0.5, 0.7))
        self.assertEqual(classify_batch(filt, ["OJK Ungkap 7 Fakta Menarik Reksa Dana Syariah"], ["ekonomi"]), [False])

    def test_no_second_copy_of_the_decision_exists_in_the_script(self):
        # The regression DBT-29/DBT-31 were about: a private re-implementation
        # of the gate or the score drifting from the live one.
        import inspect
        import scripts.backfill_sitemap_crawl_status as mod
        src = inspect.getsource(mod.classify_batch)
        for forbidden in ("category_gate(", "is_offtopic_category(", "cos_sim", "interest_embeddings", "filter_.threshold",
                          "filter_.model", "filter_.probe"):
            self.assertNotIn(forbidden, src, f"classify_batch re-implements part of the live decision: {forbidden}")
        self.assertIn("filter_.classify_batch(", src)
