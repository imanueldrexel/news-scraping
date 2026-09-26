"""SRC-54 (#177): the nested-<p> helpers in core/utils/utils.py."""
from bs4 import BeautifulSoup

from newscrawler.core.utils.utils import cascaded_pairs, is_cascaded, own_paragraph_text

A = "Paragraf pertama tentang laba bersih emiten naik tajam."
B = "Paragraf kedua tentang rencana dividen tahun depan."
C = "Paragraf ketiga menutup artikel dengan jadwal RUPS."


class TestOwnParagraphText:
    def test_skips_nested_paragraphs_keeps_inline_markup(self):
        soup = BeautifulSoup("<p><strong>Jakarta -</strong> %s<p>%s<p>%s" % (A, B, C), "html.parser")
        outer = soup.find("p")
        assert own_paragraph_text(outer) == "Jakarta - " + A
        assert own_paragraph_text(outer.find("p")) == B

    def test_closed_paragraph_is_its_whole_text(self):
        soup = BeautifulSoup("<p>%s <a href='#'>tautan</a> selesai.</p>" % A, "html.parser")
        assert own_paragraph_text(soup.p) == A + " tautan selesai."

    def test_heading_only_paragraph(self):
        soup = BeautifulSoup("<p><strong>Subjudul</strong><p>%s" % B, "html.parser")
        assert own_paragraph_text(soup.p) == "Subjudul"


class TestCascadeDetector:
    def test_suffix_cascade_is_detected(self):
        cascade = [A + " " + B + " " + C, B + " " + C, C]
        assert cascaded_pairs(cascade) == 2
        assert is_cascaded(cascade)

    def test_one_long_echo_is_one_pair_but_not_a_cascade(self):
        """DBT-46 (#188): the threshold is two pairs. A single pair (a closing
        sentence repeated as its own paragraph, as in the one WARTAEKONOMI
        article of 33,859 that has one) must not turn a healthy source's
        check_crawlers line REPEATED."""
        body = [A, B + " " + C, C]
        assert len(C) >= 20
        assert cascaded_pairs(body) == 1
        assert not is_cascaded(body)

    def test_clean_body_is_zero(self):
        assert cascaded_pairs([A, B, C]) == 0
        assert not is_cascaded([A, B, C])

    def test_short_echo_is_not_a_cascade(self):
        # "(*)" or a sign-off repeated at the end of a paragraph is not a cascade
        assert cascaded_pairs([A + " (*)", "(*)", B + " ***", "***"]) == 0

    def test_identical_consecutive_paragraphs_are_not_counted(self):
        # a duplicate is a different defect; the cascade signature is a strict suffix
        assert cascaded_pairs([A, A]) == 0

    def test_empty_and_none(self):
        assert cascaded_pairs(None) == 0
        assert cascaded_pairs(["", "  "]) == 0
