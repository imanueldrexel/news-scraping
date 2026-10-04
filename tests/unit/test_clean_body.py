"""SYS-63 (#204): one cleaner removes page chrome and related-headline lines from
every extractor's output.

The boilerplate lines below are real: each is a line stored in `articles.extracted_text`
on 2026-10-01..03 for the source named (pulled read-only). The prose lines are
real article sentences, so a pattern that over-reaches fails here."""
import pytest
from bs4 import BeautifulSoup

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.utils.utils import clean_body_paragraphs, is_boilerplate_line
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

REAL_BOILERPLATE = [
    ("BERITASATU", "BACA JUGA"),
    ("KONTAN", "Baca Juga: Argentina Buka Jalur Kewarganegaraan Bagi Investor, Modalnya Mulai US$ 350.000"),
    ("WARTAEKONOMI", "Baca Juga: DJP Kantongi Rp817,61 Miliar dari Penindakan Wajib Pajak Sektor Baja"),
    ("ANTARANEWS", "Baca juga: Menhub menyerahkan status tersangka masinis KA Bromo Anggrek ke aparat"),
    ("MEDIAINDONESIA", "Baca juga : Kemkomdigi Evaluasi Perlindungan Sisa Kuota Internet Tiga Operator Seluler"),
    ("MEDIAINDONESIA", "Baca juga : SoliDEO Festival 2026 Diikuti 129 Sekolah Bersatu dalam Semangat 'Victory in Diversity'."),
    ("BERITASATU", "Baca Selengkapnya: Wantimpres Bantu Prabowo Ambil Kebijakan Lebih Terarah dan Terukur"),
    ("LIPUTAN6", "Berita selengkapnya baca di sini"),
    ("DETIK", "Lihat juga Video: Harga Bitcoin Sentuh Rp 1,8 M, Apa Penyebabnya?"),
    ("DETIK", "Lihat juga Video Warga Irak Rayakan Kepergian Pasukan AS dari Negaranya"),
    ("DETIK", "Baca selengkapnya di detikFinance ."),
    ("KOMPAS", "Baca selengkapnya melalui tautan ini ."),
    ("PIKIRANRAKYAT", "Baca Juga: Ditjen Pas Mundur Usai Temuan Hunian Mewah dan Dugaan Pungli di Lapas Cibinong"),
    ("DETIK", "SCROLL TO CONTINUE WITH CONTENT"),
    ("TVONENEWS", "ADVERTISEMENT"),
    ("TVONENEWS", "GULIR UNTUK LANJUT BACA"),
    ("LIPUTAN6", "Advertisement"),
    ("MERDEKA", "Advertisement"),
    ("VIVA", "ADVERTISEMENT"),
    ("VIVA", "GULIR UNTUK LANJUT BACA"),
    ("CNBC", "(fsd/fsd) [Gambas:Video CNBC]"),
    ("CNN", "Lihat Juga : |"),
    ("CNN", "Lihat Juga :EDUKASI KEUANGAN Financial Check-up Tengah Tahun: Sudah Sehatkah Keuangan Anda? |"),
    ("DETIK", "Tautan telah disalin"),
    ("DETIK", "Berita selengkapnya tentang Kunjungi"),
    ("KONTAN", "Cek Berita dan Artikel yang lain di Google News"),
    ("PIKIRANRAKYAT", "Dapatkan juga informasi terkini di MantraSukabumi.com melalui Google News dengan klik tautan berikut: KLIK DISINI"),
    ("ANY", "Ikuti kami di Google News"),
    ("ANY", "Ikuti saluran WhatsApp Channel kami untuk berita terkini"),
    ("ANY", "(ega/ega)"),
]

PROSE = [
    "Bank Indonesia menahan suku bunga acuan di level enam persen pada rapat bulan ini.",
    '"Mari kita jaga lingkungan kita bersama. Pencegahan jauh lebih baik," pungkas Heri.',
    "Pemerintah China belum menyampaikan sikap.",
    # mentions a vocabulary word without being the page's chrome
    "Berita ini dilaporkan Google News Initiative bersama sejumlah penerbit.",
    "Belanja advertisement perusahaan naik 12 persen sepanjang kuartal ketiga.",
    "Pembaca dapat baca juga laporan lengkapnya di situs resmi kementerian.",
    "Pasar menunggu rilis data (yoy/qoq) pekan depan.",
    "Pertemuan AS/NATO (AS/NATO) digelar di Brussel.",
    "Ia meminta warga untuk ikuti arahan petugas dan jangan panik.",
    "Cek fakta menunjukkan klaim itu keliru, kata juru bicara.",
    "Dapatkan hasil lengkap pemungutan suara dari komisi pemilihan, kata Ketua KPU.",
    # starts with a vocabulary word but is a sentence
    "Advertisement belanja perusahaan naik 12 persen sepanjang kuartal ketiga.",
    # initials are lowercase editor tags; an upper-case pair is an abbreviation
    "(AS/NATO)",
    # SYS-72 (#220): QA's four probes -- sentences that begin with a chrome word
    "Lihat juga data BPS yang menunjukkan inflasi turun.",
    "Baca juga data BPS yang menunjukkan inflasi turun.",
    "Cek harga emas hari ini di Google News",
    "Berita selengkapnya dapat dibaca di situs resmi kementerian.",
    "(yoy/qoq)",
    "(and/or)",
]


class TestSys72ProseThatLooksLikeChrome:
    """SYS-72 (#220): the cleaner's own comments promised these survive; QA showed they did not."""

    @pytest.mark.parametrize("tail", ["(and/or)", "(yoy/qoq)", "(mom/ytd)"])
    def test_a_closing_abbreviation_pair_is_not_an_editor_tag(self, tail):
        assert clean_body_paragraphs([f"Pemerintah akan menaikkan tarif. {tail}"]) == [f"Pemerintah akan menaikkan tarif. {tail}"]

    def test_a_pair_after_a_word_not_a_sentence_end_is_not_cut(self):
        assert clean_body_paragraphs(["Harga naik 5% (yoy/qoq)"]) == ["Harga naik 5% (yoy/qoq)"]

    @pytest.mark.parametrize("body,expected", [
        ("Isi berita selesai.\n(mae/mae)", "Isi berita selesai."),
        ("Isi berita selesai. (ega/ega)", "Isi berita selesai."),
        ("Terdakwa dituntut tiga tahun. (rea/rir)", "Terdakwa dituntut tiga tahun."),
    ])
    def test_a_real_editor_tag_after_a_sentence_end_is_still_cut(self, body, expected):
        assert clean_body_paragraphs([body]) == [expected]

    def test_a_sentence_between_related_lines_is_kept_and_the_lines_go(self):
        paragraph = ("Baca Juga: Pemerintah Gelontorkan Bantuan Pangan di Kuartal IV\n"
                     "Lihat juga data BPS yang menunjukkan inflasi turun.\n"
                     "Lihat Juga :EDUKASI KEUANGAN Financial Check-up Tengah Tahun |")
        assert clean_body_paragraphs([paragraph]) == ["Lihat juga data BPS yang menunjukkan inflasi turun."]

    @pytest.mark.parametrize("line", ["Baca selengkapnya di sini .", "Baca selengkapnya >>>", "Baca selengkapnya ."])
    def test_the_read_more_stub_shapes_seen_in_stored_bodies_still_go(self, line):
        assert is_boilerplate_line(line)


@pytest.mark.parametrize("source,line", REAL_BOILERPLATE)
def test_a_real_boilerplate_line_is_recognised(source, line):
    assert is_boilerplate_line(line), f"{source}: {line!r}"


@pytest.mark.parametrize("line", PROSE)
def test_prose_is_never_boilerplate(line):
    assert not is_boilerplate_line(line)


class TestCleanBodyParagraphs:
    def test_a_related_line_inside_a_paragraph_is_cut_and_the_rest_kept(self):
        """KONTAN/trafilatura keep 'Baca Juga: ...' as a line in the middle of a paragraph."""
        paragraph = ("Penjualan mobil turun di bawah Rp 10 juta per unit.\n"
                     "Baca Juga: Pemerintah Gelontorkan Bantuan Pangan dan BSU di Kuartal IV\n"
                     "Analis memperkirakan permintaan pulih pada kuartal berikutnya.")
        assert clean_body_paragraphs([paragraph]) == [
            "Penjualan mobil turun di bawah Rp 10 juta per unit.\n"
            "Analis memperkirakan permintaan pulih pada kuartal berikutnya."]

    def test_a_paragraph_that_is_only_boilerplate_disappears(self):
        assert clean_body_paragraphs(["Isi berita.", "ADVERTISEMENT", "GULIR UNTUK LANJUT BACA", "Lanjutan."]) == [
            "Isi berita.", "Lanjutan."]

    def test_a_body_of_only_boilerplate_is_empty_not_none(self):
        assert clean_body_paragraphs(["BACA JUGA", "Advertisement"]) == []

    def test_the_shape_of_the_input_is_kept(self):
        assert clean_body_paragraphs(None) is None
        assert clean_body_paragraphs([]) == []
        assert clean_body_paragraphs("Isi.\nBaca juga: Lain\nLanjut.") == "Isi.\nLanjut."
        assert clean_body_paragraphs(("Isi.", "Advertisement")) == ["Isi."]

    def test_prose_paragraphs_come_back_unchanged(self):
        assert clean_body_paragraphs(list(PROSE)) == PROSE

    def test_a_paragraph_with_nothing_to_remove_is_not_touched_at_all(self):
        body = ["Isi dengan spasi di ujung. ", "  Dibuka spasi.", "", "Baris satu.\nBaris dua."]
        assert clean_body_paragraphs(list(body)) == body

    def test_an_editor_tail_is_cut_from_the_last_line_only(self):
        assert clean_body_paragraphs(["Isi berita.", "Pernyataan itu disampaikan Selasa. (ega/ega)"]) == [
            "Isi berita.", "Pernyataan itu disampaikan Selasa."]
        # not at the end of the body: kept
        assert clean_body_paragraphs(["Isi (ega/ega) tengah.", "Penutup."]) == ["Isi (ega/ega) tengah.", "Penutup."]

    def test_a_widget_after_initials_takes_the_whole_line(self):
        """CNBC ends '(fsd/fsd) [Gambas:Video CNBC]' on one line."""
        assert clean_body_paragraphs(["Isi.", "(fsd/fsd) [Gambas:Video CNBC]"]) == ["Isi."]

    def test_idempotent(self):
        body = ["Isi.", "Baca Juga: X", "Advertisement", "Penutup (abc/abc)"]
        once = clean_body_paragraphs(body)
        assert clean_body_paragraphs(once) == once


BODY = "Bank Indonesia menahan suku bunga acuan di level enam persen pada rapat bulan ini. " * 5


class _Loader:
    def get_soup(self, url):
        return BeautifulSoup(f"<html><body><article><p>{BODY}</p></article></body></html>", "html.parser")


def _crawler(primary, site_text=None, traf=None, newspaper=None):
    class C(Crawler):
        PRIMARY_EXTRACTOR = primary

        def _get_whole_text(self_, soup):
            return site_text

        def _get_reporter_from_text(self_, soup):
            return []
    c = C()
    c.website_name = "TEST"
    c.page_loader = _Loader()
    c._trafilatura_fallback = lambda soup: traf
    c._newspaper_fallback = lambda url: newspaper
    return c


def _text(crawler):
    dto, reason = crawler._fetch_news_details(
        SitemapDTO(headline="h", link="http://x/1", sources="TEST", sitemap_id=1))
    assert reason is None, reason
    return dto, "\n".join(dto.extracted_text)


DIRTY = [BODY, "Baca Juga: Berita Lain yang Tidak Terkait", "ADVERTISEMENT"]


class TestEveryExtractorPathIsCleaned:
    def test_site_extractor(self):
        dto, text = _text(_crawler("site", site_text=list(DIRTY)))
        assert dto.meta_data["extractor"] == "site"
        assert "Baca Juga" not in text and "ADVERTISEMENT" not in text and BODY.strip() in text

    def test_trafilatura_as_the_declared_extractor(self):
        dto, text = _text(_crawler("trafilatura", traf=list(DIRTY)))
        assert dto.meta_data["extractor"] == "trafilatura"
        assert "Baca Juga" not in text and "ADVERTISEMENT" not in text

    def test_trafilatura_as_the_fallback_of_a_dead_site_selector(self):
        dto, text = _text(_crawler("site", site_text=None, traf=list(DIRTY)))
        assert dto.meta_data["extractor"] == "trafilatura"
        assert "Baca Juga" not in text

    def test_newspaper_as_the_last_resort(self):
        dto, text = _text(_crawler("site", site_text=None, traf=None, newspaper=list(DIRTY)))
        assert dto.meta_data["extractor"] == "newspaper"
        assert "Baca Juga" not in text and "ADVERTISEMENT" not in text

    def test_a_body_that_is_only_chrome_falls_through_to_the_next_extractor(self):
        """Cleaning happens before the usable-text check, so a selector that now
        yields nothing hands over to trafilatura instead of storing an empty body."""
        chrome = ["Baca Juga: " + "Judul Panjang " * 12, "ADVERTISEMENT"]
        dto, text = _text(_crawler("site", site_text=chrome, traf=[BODY]))
        assert dto.meta_data["extractor"] == "trafilatura"
        assert text.strip() == BODY.strip()


class TestFleet:
    @pytest.mark.parametrize("name", sorted(CRAWLER_DICT))
    def test_no_crawler_bypasses_the_cleaned_fetch_path(self, name):
        """The cleaner lives in the base fetch; a subclass that replaced it would
        quietly store dirty bodies again."""
        cls = type(CRAWLER_DICT[name])
        for method in ("_fetch_news_details", "_get_news_details"):
            assert getattr(cls, method) is getattr(Crawler, method), f"{name} overrides {method}"
