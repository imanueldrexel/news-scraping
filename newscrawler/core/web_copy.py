"""Every string a reader of the search page ("Tanya Berita") sees, in one place (SYS-101 #270).

The templates hold no literal reader text; they render these names (a unit test
parses the templates to enforce it). Dates, outlet names and section names come
from `newsletter_copy`, so the page and the newsletter never disagree (SYS-95).

Glossary, reader-facing: artikel = one document, portal = an outlet, topik = a
section, sumber = the list behind an answer. Never chunk, query, RAG, kategori or
konteks. Register: neutral journalistic Indonesian; the reader is "Anda" when
addressed at all. Telemetry (timings, scores, the model) belongs in the log.
"""
from datetime import date, datetime
from typing import Optional

from newscrawler.core import newsletter_copy as nc

# ── Page, hero, search ──────────────────────────────────────────────────────
PAGE_TITLE = "Tanya Berita · NewsAggregator"
TITLE = "Tanya Berita"
HERO_HEADING = "Tanyakan apa saja tentang berita Indonesia hari ini."
HERO_LINE = ("Jawaban disusun dari {n} artikel di {portals} portal berita, lengkap dengan sumbernya. "
             "Diperbarui {kapan}.")
HERO_LINE_NO_STATS = "Jawaban disusun dari artikel portal berita Indonesia, lengkap dengan sumbernya."
QUESTION_LABEL = "Pertanyaan"
PLACEHOLDER = "Contoh: Kenapa rupiah melemah pekan ini?"
ASK = "Tanya"
EXAMPLES_LABEL = "Contoh pertanyaan"
EXAMPLES = (
    "Apa isi RUU Ketenagakerjaan yang baru disahkan?",
    "Bagaimana kinerja IHSG pekan ini?",
    "Apa kata OJK soal kredit perbankan?",
)
QUESTION_TOO_LONG = "Pertanyaan terlalu panjang; maksimal {n} karakter."
QUESTION_EMPTY = "Tulis pertanyaan Anda dulu."

# ── Filters (SYS-100) ───────────────────────────────────────────────────────
FILTER_TOGGLE = "Filter"
TOPIC_LABEL = "Topik"
TOPIC_ALL = "Semua topik"
PORTAL_LABEL = "Portal"
PORTAL_ALL = "Semua portal"
DATE_LABEL = "Tanggal"
DATE_ALL = "Semua"
DATE_7 = "7 hari"
DATE_30 = "30 hari"
DATE_CUSTOM = "Pilih tanggal"
DATE_FROM = "Dari"
DATE_TO = "Sampai"
ACTIVE_FILTERS_LABEL = "Filter aktif"
REMOVE_FILTER = "Hapus filter {label}"
RANGE_LAST = "{n} hari terakhir"
CLEAR_FILTERS = "Hapus filter"

# ── Thread, loading, answer, sources ────────────────────────────────────────
LOADING_SEARCH = "Mencari artikel yang relevan…"
LOADING_ANSWER = "Menyusun jawaban dari {n} artikel…"
DISCLOSURE = "Disusun AI dari artikel sumber dan bisa keliru. Cek sumbernya untuk detail."
SOURCES_HEADER = "Berdasarkan {n} artikel"
READ_AT = nc.READ_AT                              # "Baca di {outlet} →", as in the newsletter
CITE_LABEL = "Sumber {n}"
FOLLOWUP_LABEL = "Tanya lanjutan tentang topik ini…"
NEW_QUESTION = "Pertanyaan baru"

# The answer prompt's fixed sentence for thin evidence (SYS-99); the model writes it verbatim.
NOT_ENOUGH = "Artikel yang ada belum cukup untuk menjawab ini dengan pasti."

# ── States (SYS-94, SYS-99, SYS-101) ────────────────────────────────────────
NO_HITS = "Belum ada artikel yang membahas ini. Coba kata lain atau perluas rentang tanggal."
NARROW = "Tidak ada artikel{topik}{portal}{rentang}."
UNAVAILABLE = "Ringkasan AI sedang tidak tersedia. Berikut artikel yang paling relevan dengan pertanyaan Anda."
# PM's text said "tersedia di bawah"; on desktop the sources sit beside the answer, so it names the list.
FAILED = "Jawaban gagal disusun. Artikel yang relevan tetap bisa dibaca di daftar sumber."
FAILED_NO_SOURCES = "Jawaban gagal disusun. Coba lagi sebentar lagi."
RETRY = "Coba lagi"
UNVERIFIED = "Sebagian angka belum terverifikasi; cek sumbernya."
EXPIRED = "Pertanyaan ini sudah kedaluwarsa. Ajukan lagi untuk melihat jawabannya."


def angka(n: int) -> str:
    return nc.angka(n)


def tanggal_singkat(d: date) -> str:
    """'5 Okt 2026': inside a sentence or a filter chip, where the weekday is noise."""
    return f"{d.day} {nc.MONTHS_SHORT[d.month - 1]} {d.year}"


def tanggal_kartu(d: Optional[date]) -> str:
    """A source card's date, 'Senin, 5 Okt 2026'; '' when unknown."""
    return nc.tanggal_pendek(d) if d else ""


def kapan(moment: datetime, today: date) -> str:
    """'pukul 20.16 WIB' today, 'Selasa, 6 Okt 2026 pukul 20.16 WIB' before. `moment` is WIB."""
    jam = f"pukul {moment.hour:02d}.{moment.minute:02d} WIB"
    return jam if moment.date() == today else f"{nc.tanggal_pendek(moment.date())} {jam}"


def hero_line(articles: Optional[int], portals: Optional[int], updated: Optional[datetime], today: date) -> str:
    if not articles or not portals or updated is None:
        return HERO_LINE_NO_STATS
    return HERO_LINE.format(n=angka(articles), portals=angka(portals), kapan=kapan(updated, today))


def topic_name(topic: Optional[str]) -> str:
    """The section name a reader knows ('Pasar'); '' for no or an unknown topic."""
    return nc.SECTION_NAMES.get(topic or "", "")


def range_chip(days: Optional[int], date_from: Optional[date], date_to: Optional[date]) -> str:
    """The active-filter chip for the date range; '' when there is none."""
    if days:
        return RANGE_LAST.format(n=days)
    if date_from and date_to:
        return f"{tanggal_singkat(date_from)} – {tanggal_singkat(date_to)}"
    if date_from:
        return f"Sejak {tanggal_singkat(date_from)}"
    if date_to:
        return f"Hingga {tanggal_singkat(date_to)}"
    return ""


def _range_phrase(days: Optional[int], date_from: Optional[date], date_to: Optional[date]) -> str:
    if days:
        return f" dalam {RANGE_LAST.format(n=days)}"
    if date_from and date_to:
        return f" antara {tanggal_singkat(date_from)} dan {tanggal_singkat(date_to)}"
    if date_from:
        return f" sejak {tanggal_singkat(date_from)}"
    if date_to:
        return f" hingga {tanggal_singkat(date_to)}"
    return ""


def narrow(topic: Optional[str], source: Optional[str], days: Optional[int],
           date_from: Optional[date], date_to: Optional[date]) -> str:
    """'Tidak ada artikel Pasar dari Kontan dalam 7 hari terakhir.' -- only the set filters."""
    name = topic_name(topic)
    return NARROW.format(topik=f" {name}" if name else "",
                         portal=f" dari {nc.outlet(source)}" if source else "",
                         rentang=_range_phrase(days, date_from, date_to))
