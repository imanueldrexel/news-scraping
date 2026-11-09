"""SYS-81 (#237) Indonesian dates, SYS-84 (#241) the reader's wording, SYS-85 (#245)
the authority table's keys.

The rendered documents are checked whole: no English month, no ISO date, no model
name or cluster count, no internal source name -- on a host whose locale is English.
"""
import locale
import logging
import re
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_copy as copy
import newscrawler.core.newsletter_generator as ng
from newscrawler.core.constants import SOURCE_AUTHORITY
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from tests.unit.newsletter_fakes import FakeNewsroom, story_answer

# The English month names that are not also Indonesian ones (April, September, November are both).
ENGLISH_MONTHS = re.compile(r"\b(January|February|March|May|June|July|August|October|December)\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


@pytest.fixture
def english_locale():
    """The scheduled host's locale is English; a date built with strftime('%B') would show it."""
    old = locale.setlocale(locale.LC_TIME)
    for name in ("English_United States.1252", "en_US.UTF-8", "en_US", "C"):
        try:
            locale.setlocale(locale.LC_TIME, name)
            break
        except locale.Error:
            continue
    yield
    locale.setlocale(locale.LC_TIME, old)


class TestDates:
    def test_the_digest_date(self, english_locale):
        assert copy.tanggal(date(2026, 10, 4)) == "Minggu, 4 Oktober 2026"
        assert copy.tanggal_pendek(date(2026, 10, 4)) == "Minggu, 4 Okt 2026"

    @pytest.mark.parametrize("month,name,short", [
        (1, "Januari", "Jan"), (2, "Februari", "Feb"), (3, "Maret", "Mar"), (4, "April", "Apr"), (5, "Mei", "Mei"),
        (6, "Juni", "Jun"), (7, "Juli", "Jul"), (8, "Agustus", "Agu"), (9, "September", "Sep"),
        (10, "Oktober", "Okt"), (11, "November", "Nov"), (12, "Desember", "Des")])
    def test_every_month(self, month, name, short, english_locale):
        d = date(2026, month, 15)
        assert copy.tanggal(d).endswith(f" 15 {name} 2026")
        assert copy.tanggal_pendek(d).endswith(f" 15 {short} 2026")

    def test_every_day_of_the_week(self, english_locale):
        monday = date(2026, 10, 5)                 # a Monday
        days = [copy.tanggal(monday + timedelta(days=k)).split(",")[0] for k in range(7)]
        assert days == ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

    def test_no_leading_zero(self):
        assert copy.tanggal(date(2026, 3, 1)) == "Minggu, 1 Maret 2026"

    def test_counts_use_indonesian_thousands(self):
        assert (copy.angka(1798), copy.angka(12), copy.angka(1234567)) == ("1.798", "12", "1.234.567")


class TestOutletNames:
    def test_every_source_has_a_brand_name(self):
        missing = [w.value for w in WebsiteName if w.value not in copy.OUTLET_NAMES]
        assert missing == []

    def test_the_names_a_reader_knows(self):
        assert [copy.outlet(s) for s in ("KONTAN", "INVESTORID", "PIKIRANRAKYAT", "CNN", "CNBC", "TRIBUN", "DETIK")] \
            == ["Kontan", "Investor.id", "Pikiran Rakyat", "CNN Indonesia", "CNBC Indonesia", "Tribunnews", "detikcom"]

    def test_the_lookup_ignores_case(self):
        assert copy.outlet("kontan") == "Kontan"

    def test_an_unknown_source_is_shown_title_cased_and_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger=copy.logger.name):
            assert copy.outlet("NEWPORTAL") == "Newportal"
        assert "NEWPORTAL" in caplog.text

    def test_the_authority_table_names_real_sources(self):
        """SYS-85 (#245): 'ANTARA' never matched the stored 'ANTARANEWS'."""
        sources = {w.value for w in WebsiteName}
        assert set(SOURCE_AUTHORITY) <= sources, set(SOURCE_AUTHORITY) - sources
        assert SOURCE_AUTHORITY["ANTARANEWS"] == 0.70


class TestSectionNames:
    def test_every_section_has_its_names(self):
        for table in (copy.SECTION_NAMES, copy.SECTION_TITLES, copy.SECTION_SHORT):
            assert set(table) == set(ng.SECTION_ORDER)
        assert ng.SECTION_TITLES is copy.SECTION_TITLES


# ── The rendered documents ──────────────────────────────────────────────────

def _art(i, source, topic="markets", cluster=0, headline=None):
    return {"sitemap_id": i, "headline": headline or f"Berita nomor {i}", "source": source, "category": "news",
            "link": f"http://x/{i}", "posted_at": 20261004, "topic": topic, "l1_text": f"isi {i}",
            "_cluster": cluster}


DAY = [_art(1, "INVESTORID", cluster=0), _art(2, "PIKIRANRAKYAT", cluster=0), _art(3, "CNN", cluster=0),
       _art(4, "TRIBUN", "law_crime", cluster=1), _art(5, "KONTAN", "law_crime", cluster=1),
       _art(6, "DETIK", "politics_government", cluster=2), _art(7, "TVONENEWS", "politics_government", cluster=2)]


def _generate(monkeypatch, tmp_path, summarizer, arts=DAY):
    ds = MagicMock()
    gen = ng.NewsletterGenerator(ds, summarizer=summarizer, embed_documents=lambda t: [[0.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    monkeypatch.setattr(gen, "_merge_across_sections", lambda entries, vectors: entries)
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in arts])
    ds.get_articles_for_date.return_value = arts
    return gen.generate(date(2026, 10, 4)), ds


def _documents(path):
    texts = [open(path, encoding="utf-8").read()]
    if getattr(path, "edition", None):
        texts.append(open(path.edition, encoding="utf-8").read())
    return texts


class TestReaderDocuments:
    def test_a_normal_day(self, monkeypatch, tmp_path, english_locale):
        path, _ = _generate(monkeypatch, tmp_path, FakeNewsroom())
        digest, edition = _documents(path)
        assert digest.startswith("# Rangkuman Berita\n\n> Minggu, 4 Oktober 2026 · edisi lengkap\n")
        assert edition.startswith("# Rangkuman Berita\n\n> Minggu, 4 Oktober 2026 · ±5 menit baca\n")
        footer = ("Disarikan dari 7 artikel di 7 portal. "
                  "Ringkasan ditulis AI dan bisa keliru; cek artikel aslinya untuk detail.")
        assert f"*{footer}*" in digest and footer in edition
        assert "Edisi lengkap memuat 3 berita." in edition
        assert "**Diberitakan 3 portal:** Investor.id · Pikiran Rakyat · CNN Indonesia" in digest
        for heading in ("## Hari Ini dalam 60 Detik", "## Berita Utama", "**Diberitakan 3 portal** · [Baca di "):
            assert heading in edition
        assert "Sebagian ringkasan" not in digest + edition
        assert "berita lainnya di bagian ini" not in edition          # the archive's line only

    def test_no_internal_name_english_date_or_telemetry(self, monkeypatch, tmp_path, english_locale):
        path, _ = _generate(monkeypatch, tmp_path, FakeNewsroom())
        for text in _documents(path):
            prose = re.sub(r"\]\([^)]*\)", "]", text)          # link targets are URLs, not reader text
            assert not ENGLISH_MONTHS.search(prose)
            assert not ISO_DATE.search(prose)
            for internal in ("INVESTORID", "PIKIRANRAKYAT", "TRIBUN", "TVONENEWS", "KONTAN", "DETIK"):
                assert not re.search(rf"\b{internal}\b", prose), internal
            for telemetry in ("fake-model", "Cluster", "Ringkasan AI", "WIB", "Total artikel"):
                assert telemetry not in prose, telemetry

    def test_a_degraded_day_says_so_at_the_top(self, monkeypatch, tmp_path):
        s = FakeNewsroom(story=[story_answer] * 2 + ["x", "x"])     # the third story is refused twice
        path, _ = _generate(monkeypatch, tmp_path, s)
        digest = open(path, encoding="utf-8").read()
        notice = "> Sebagian ringkasan tidak tersedia hari ini. 1 berita hanya ditampilkan judulnya."
        assert notice in digest and digest.index(notice) < digest.index("## ")

    def test_an_empty_day(self, monkeypatch, tmp_path, english_locale):
        path, ds = _generate(monkeypatch, tmp_path, FakeNewsroom(), arts=[])
        text = open(path, encoding="utf-8").read()
        assert text == ("# Rangkuman Berita\n\n> Minggu, 4 Oktober 2026 · edisi lengkap\n\n"
                        "Tidak ada berita yang terkumpul untuk Minggu, 4 Oktober 2026. "
                        "Ini biasanya tanda gangguan pengumpulan, bukan hari tanpa berita.\n")
        assert path.edition is None and ds.save_digest.call_args.kwargs["article_count"] == 0

    def test_an_empty_day_removes_a_stale_edition_of_that_date(self, monkeypatch, tmp_path):
        stale = tmp_path / "2026-10-04-ringkas.md"
        stale.write_text("old", encoding="utf-8")
        _generate(monkeypatch, tmp_path, FakeNewsroom(), arts=[])
        assert not stale.exists()
