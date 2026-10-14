"""DBT-72 (#344): the one module that holds generated text to its sources, and
SYS-153 (#343): a written-out date is a date, not the bare number of its day.

The number-by-value and subject cases stay in test_story_summary.py (they test
the summary's guard through these functions); this file covers what DBT-72 adds
and the rule that no other module defines its own copy."""
import ast
import os
from datetime import date, timedelta

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


class TestDateMentions:
    def test_positions_and_forms_valid_months_only(self):
        assert sc.date_mentions("Pada 24/9 dan 6 Okt; skor 3/13") == [(5, 24, 9, "24/9"), (14, 6, 10, "6 Okt")]


class TestResolve:
    @pytest.mark.parametrize("day,month,expected", [
        (24, 9, date(2026, 9, 24)), (15, 10, date(2026, 10, 15)),        # past, or a scheduled date this month
        (10, 11, date(2026, 11, 10)),                                    # within a month ahead
        (20, 12, date(2025, 12, 20)),                                    # further ahead: last year's
        (31, 9, None),
    ])
    def test_the_nearest_sensible_year(self, day, month, expected):
        assert sc.resolve(day, month, TODAY) == expected


TODAY = date(2026, 10, 12)        # a Monday


class TestRelativeTimes:
    """SYS-157 (#352): the days each relative phrase can mean, seen from the edition's date."""

    @pytest.mark.parametrize("text,first,last", [
        ("awal Oktober", date(2026, 10, 1), date(2026, 10, 10)),
        ("pertengahan September", date(2026, 9, 11), date(2026, 9, 20)),
        ("akhir September", date(2026, 9, 21), date(2026, 9, 30)),
        ("akhir Februari", date(2026, 2, 21), date(2026, 2, 28)),
        ("akhir Desember", date(2025, 12, 21), date(2025, 12, 31)),       # a later month is last year's
        ("awal bulan ini", date(2026, 10, 1), date(2026, 10, 10)),
        ("awal bulan", date(2026, 10, 1), date(2026, 10, 10)),
        ("akhir bulan lalu", date(2026, 9, 21), date(2026, 9, 30)),
        ("sejak September", date(2026, 9, 1), date(2026, 9, 30)),
        ("bulan lalu", date(2026, 9, 1), date(2026, 9, 30)),
        ("pekan lalu", date(2026, 10, 5), date(2026, 10, 11)),
        ("minggu lalu", date(2026, 10, 5), date(2026, 10, 11)),
        ("sepekan lalu", date(2026, 10, 3), date(2026, 10, 7)),
        ("seminggu sebelumnya", date(2026, 10, 3), date(2026, 10, 7)),
        ("dua pekan lalu", date(2026, 9, 25), date(2026, 10, 1)),
        ("sepekan terakhir", date(2026, 10, 5), date(2026, 10, 11)),
        ("dua pekan terakhir", date(2026, 9, 28), date(2026, 10, 11)),
        ("Kamis lalu", date(2026, 10, 8), date(2026, 10, 8)),
        ("Senin lalu", date(2026, 10, 5), date(2026, 10, 5)),           # today is a Monday: a week back
        ("Minggu lalu", date(2026, 10, 11), date(2026, 10, 11)),
        ("kemarin", date(2026, 10, 11), date(2026, 10, 11)),
        ("tiga hari lalu", date(2026, 10, 8), date(2026, 10, 10)),
        ("2 hari sebelumnya", date(2026, 10, 9), date(2026, 10, 11)),
    ])
    def test_each_phrase_family(self, text, first, last):
        assert sc.relative_times(f"Hal itu terjadi {text}.", TODAY) == [(text, first, last)]

    def test_the_longest_phrase_wins(self):
        assert [p for p, *_ in sc.relative_times("dua pekan lalu dan sejak awal Oktober", TODAY)] == [
            "dua pekan lalu", "awal Oktober"]

    @pytest.mark.parametrize("text", ["pada 24 September lalu", "sejak 24 September", "pada awal pekan",
                                      "sepekan kemudian", "hari ini"])
    def test_not_a_relative_phrase(self, text):
        assert sc.relative_times(text, TODAY) == []


class TestRelativeName:
    """The phrase shown beside each timeline item: the check must accept it for that item."""

    @pytest.mark.parametrize("today", [date(2026, 10, 12), date(2026, 10, 18), date(2026, 3, 2), date(2026, 1, 1)])
    def test_every_past_day_reads_back_as_a_span_holding_it(self, today):
        for back in range(1, 32):
            day = today - timedelta(days=back)
            spans = sc.relative_times(sc.relative_name(day, today), today)
            assert len(spans) == 1 and spans[0][1] <= day <= spans[0][2], (day, sc.relative_name(day, today))

    @pytest.mark.parametrize("day,name", [(date(2026, 10, 11), "kemarin"), (date(2026, 10, 7), "pekan lalu"),
                                          (date(2026, 10, 2), "awal Oktober"), (date(2026, 9, 23), "akhir September"),
                                          (date(2026, 9, 15), "pertengahan September")])
    def test_names(self, day, name):
        assert sc.relative_name(day, TODAY) == name


class TestOrdinalClaims:
    """SYS-158 (#353): counts and records the writer inferred."""

    @pytest.mark.parametrize("text,claim,n,key", [
        ("Ini gelombang kedua perombakan Polri.", "gelombang kedua", 2, "gelombang 2"),
        ("Rapat digelar untuk ketiga kalinya.", "ketiga kalinya", 3, "kali 3"),
        ("IHSG turun pada pekan kedua beruntun.", "pekan kedua", 2, "pekan 2"),
        ("Pemilu ke-5 digelar.", "ke-5", 5, "ke-5"),
        ("Rupiah melemah untuk kesekian kalinya.", "kesekian kalinya", 3, "kesekian"),
        ("IHSG turun tiga hari berturut-turut.", "tiga hari berturut-turut", 3, "beruntun hari 3"),
        ("IHSG turun enam hari perdagangan beruntun.", "enam hari perdagangan beruntun", 6, "beruntun hari 6"),
        ("IHSG di level terendah sejak Maret 2026.", "terendah sejak Maret", None, "terendah sejak maret"),
        ("Inflasi naik pertama kalinya sejak 2019.", "pertama kalinya sejak 2019", None, "pertama kali sejak 2019"),
    ])
    def test_a_claim(self, text, claim, n, key):
        assert sc.ordinal_claims(text) == [(claim, n, key)]

    @pytest.mark.parametrize("text", ["Kedua negara sepakat.", "Presiden dan kedua menteri hadir.",
                                      "antara ketiga tersangka", "pada kuartal pertama", "IHSG turun beruntun"])
    def test_not_a_claim(self, text):
        """A collective 'kedua' (both) follows a function word or opens the sentence."""
        assert sc.ordinal_claims(text) == []


# The check functions DBT-72 gathered here; a module that needs one imports it.
_CHECKS = {"values", "_canonical", "_date_in", "unsupported_number", "dates_in", "off_subject", "relative_times",
           "ordinal_claims", "resolve", "date_mentions"}
_CALLERS = ["newscrawler/core/story_summary.py", "newscrawler/core/newsletter_edition.py",
            "newscrawler/core/story_arc.py", "newscrawler/web/answer.py", "newscrawler/core/arc_style.py"]


@pytest.mark.parametrize("path", _CALLERS)
def test_no_caller_defines_its_own_check(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        pytest.skip(f"{path} does not exist yet")
    tree = ast.parse(open(full, encoding="utf-8").read())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not defined & _CHECKS, f"{path} defines {sorted(defined & _CHECKS)}: import it from source_check"
