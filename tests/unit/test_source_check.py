"""DBT-72 (#344): the one module that holds generated text to its sources, and
SYS-153 (#343): a written-out date is a date, not the bare number of its day.

The number-by-value and subject cases stay in test_story_summary.py (they test
the summary's guard through these functions); this file covers what DBT-72 adds
and the rule that no other module defines its own copy."""
import ast
import os

import pytest

import newscrawler.core.source_check as sc

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWrittenOutDates:
    """SYS-153: 'Pada 24 September' passed against any source holding a 24."""

    def test_the_sys153_repro_is_refused(self):
        assert sc.unsupported_number("Pada 24 September Prabowo menggelar rapat.",
                                     "Inflasi naik 24 persen pada 12/10.") == "24 September"

    @pytest.mark.parametrize("source", ["Rapat digelar Rabu (24/9).", "Pada 24 September 2026 rapat digelar.",
                                        "rapat 24 Sep", "rapat 24/09/2026"])
    def test_a_written_out_date_passes_when_the_source_names_that_date(self, source):
        assert sc.unsupported_number("Pada 24 September Prabowo menggelar rapat.", source) is None

    @pytest.mark.parametrize("text,written", [
        ("pada 2 Okt", "2 Okt"), ("sejak 5 Agustus 2026", "5 Agustus 2026"), ("hingga 31 desember", "31 desember"),
        ("pada 1 Mei", "1 Mei"),
    ])
    def test_short_and_full_month_names_with_or_without_a_year(self, text, written):
        assert sc.unsupported_number(text, "Tidak ada tanggal di sini.") == written

    def test_the_year_of_a_written_out_date_is_not_a_separate_number(self):
        assert sc.unsupported_number("pada 24 September 2026", "Kamis (24/9) rapat digelar.") is None

    def test_a_month_inside_a_longer_word_is_not_a_date(self):
        """'Mei' in 'Meikarta' is not May: 3 must then be in the source as a number."""
        assert sc.unsupported_number("3 Meikarta", "3 menara") is None
        assert sc.unsupported_number("3 Meikarta", "menara") == "3"

    def test_a_number_ending_a_word_does_not_start_a_date(self):
        """Replay 2026-09-24: 'M2 Agustus 2026' is the money supply of August, not 2 August."""
        source = "Uang beredar (M2) pada Agustus 2026 mencapai Rp10.448,1 triliun."
        assert sc.unsupported_number("BI mencatat M2 Agustus 2026 mencapai Rp10.448,1 triliun", source) is None
        assert sc.dates_in("M2 Agustus 2026") == []

    def test_the_first_unstated_date_is_reported_in_text_order(self):
        assert sc.unsupported_number("Pada 4/10 dan 5 Oktober", "tidak ada") == "4/10"
        assert sc.unsupported_number("Pada 5 Oktober dan 4/10", "tidak ada") == "5 Oktober"


class TestKnownDates:
    """SYS-148: a timeline item's own date is right though no text states it; it licenses the date only."""

    def test_a_known_date_passes_in_either_form(self):
        assert sc.unsupported_number("Pada 24/9 dan 24 September", "tidak ada", [(24, 9)]) is None

    def test_a_known_date_does_not_make_its_digits_numbers(self):
        assert sc.unsupported_number("24 ahli dipanggil", "tidak ada", [(24, 9)]) == "24"

    def test_without_dates(self):
        assert sc.without_dates("Pada 24/9 dan 5 Okt 2026 ada 7 rapat").split() == ["Pada", "dan", "ada", "7", "rapat"]


class TestDatesIn:
    def test_every_form_in_the_order_written(self):
        assert sc.dates_in("Pada 24/9 rapat pertama, lalu 6 Okt dan 12 Oktober 2026.") == [(24, 9), (6, 10), (12, 10)]

    def test_a_score_is_not_a_date(self):
        assert sc.dates_in("skor 3/13 di babak kedua") == []

    def test_no_date(self):
        assert sc.dates_in("IHSG turun 2,59% ke 5.936") == []


# The check functions DBT-72 gathered here; a module that needs one imports it.
_CHECKS = {"values", "_canonical", "_date_in", "unsupported_number", "dates_in", "off_subject"}
_CALLERS = ["newscrawler/core/story_summary.py", "newscrawler/core/newsletter_edition.py",
            "newscrawler/core/story_arc.py", "newscrawler/web/answer.py"]


@pytest.mark.parametrize("path", _CALLERS)
def test_no_caller_defines_its_own_check(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        pytest.skip(f"{path} does not exist yet")
    tree = ast.parse(open(full, encoding="utf-8").read())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not defined & _CHECKS, f"{path} defines {sorted(defined & _CHECKS)}: import it from source_check"
