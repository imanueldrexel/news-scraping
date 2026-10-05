"""Every string a newsletter reader sees, in one place (SYS-84 #241, SYS-81 #237).

The full digest, the 5-minute edition (SYS-83), their PDFs (OPS-42) and the
Telegram message (OPS-43) all take their wording from here, so a label is
changed once and a test can assert each one.

Dates are written from explicit Indonesian tables, never `strftime("%B")`:
the scheduled host's locale is English, which is how "4 October 2026" reached
an Indonesian digest (SYS-81).

Pipeline telemetry (cluster counts, the model, the generation time) is not
here on purpose: it belongs in the log, the newsletter_digests row and the
operator's Telegram line, not in the reader's document.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

# date.weekday(): Monday is 0.
DAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember")
MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def tanggal(d: date) -> str:
    """'Minggu, 4 Oktober 2026'."""
    return f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"


def tanggal_pendek(d: date) -> str:
    """'Minggu, 4 Okt 2026': captions and the PDF footer."""
    return f"{DAYS[d.weekday()]}, {d.day} {MONTHS_SHORT[d.month - 1]} {d.year}"


def angka(n: int) -> str:
    """A count in Indonesian notation: 1798 -> '1.798'. Only for the newsletter's
    own counts; numbers inside summaries are copied from the articles (SYS-82)."""
    return f"{n:,}".replace(",", ".")


# Source enum value -> the outlet's own brand name. Every WebsiteName has one
# (a unit test enforces it); the retired sources stay so an old day still renders.
OUTLET_NAMES = {
    "ANTARANEWS":     "Antara",
    "BERITASATU":     "Beritasatu",
    "BISNIS":         "Bisnis.com",
    "CNBC":           "CNBC Indonesia",
    "CNN":            "CNN Indonesia",
    "DETIK":          "detikcom",
    "EMITENNEWS":     "Emitennews",
    "ERAID":          "Era.id",
    "IDNTIMES":       "IDN Times",
    "IDXCHANNEL":     "IDX Channel",
    "INEWS":          "iNews",
    "INVESTORID":     "Investor.id",
    "JPNN":           "JPNN",
    "KOMPAS":         "Kompas.com",
    "KONTAN":         "Kontan",
    "KUMPARAN":       "kumparan",
    "LIPUTAN6":       "Liputan6",
    "MEDIAINDONESIA": "Media Indonesia",
    "MERDEKA":        "Merdeka.com",
    "OKEZONE":        "Okezone",
    "PIKIRANRAKYAT":  "Pikiran Rakyat",
    "SINDONEWS":      "SINDOnews",
    "SUARA":          "Suara.com",
    "TEMPO":          "Tempo",
    "TIRTO":          "Tirto",
    "TRIBUN":         "Tribunnews",
    "TVONENEWS":      "tvOnenews",
    "VIVA":           "VIVA",
    "WARTAEKONOMI":   "Warta Ekonomi",
    # retired 2026-09 (CLAUDE.md), still in old rows
    "BATAMPOS":       "Batam Pos",
    "GRIDID":         "Grid.ID",
    "KAPANLAGI":      "KapanLagi",
}


def outlet(source: str) -> str:
    """The brand name a reader knows. A source missing from OUTLET_NAMES is
    shown title-cased and logged, so a new crawler is noticed, not hidden."""
    name = OUTLET_NAMES.get((source or "").upper())
    if name is None:
        logger.warning(f"No outlet display name for source {source!r}; add it to OUTLET_NAMES.")
        return (source or "").title()
    return name


# Section (articles.topic) names. The digest's headings carry an emoji in the
# markdown (the PDF drops it); the editor's prompt reads the plain name.
SECTION_NAMES = {
    "markets":             "Pasar",
    "macro_policy":        "Kebijakan & Makroekonomi",
    "corporate":           "Korporasi",
    "commodities_energy":  "Komoditas & Energi",
    "consumer":            "Konsumen & Bisnis",
    "politics_government": "Politik & Pemerintahan",
    "law_crime":           "Hukum & Kriminal",
    "disaster_accident":   "Bencana & Kecelakaan",
    "international":       "Internasional",
    "tech_science":        "Teknologi & Sains",
    "health_education":    "Kesehatan & Pendidikan",
    "other_news":          "Berita Lainnya",
}
_SECTION_EMOJI = {
    "markets": "📈", "macro_policy": "📊", "corporate": "🏭", "commodities_energy": "🛢️", "consumer": "🛒",
    "politics_government": "🏛️", "law_crime": "⚖️", "disaster_accident": "🚨", "international": "🌏",
    "tech_science": "🔬", "health_education": "🏥", "other_news": "📰",
}
SECTION_TITLES = {topic: f"{_SECTION_EMOJI[topic]} {name}" for topic, name in SECTION_NAMES.items()}

# Short section names for the edition's Sekilas lines ("Hukum · ...").
SECTION_SHORT = {
    "markets":             "Pasar",
    "macro_policy":        "Makro",
    "corporate":           "Korporasi",
    "commodities_energy":  "Komoditas",
    "consumer":            "Konsumen",
    "politics_government": "Politik",
    "law_crime":           "Hukum",
    "disaster_accident":   "Bencana",
    "international":       "Internasional",
    "tech_science":        "Teknologi",
    "health_education":    "Kesehatan & Pendidikan",
    "other_news":          "Lainnya",
}

TITLE = "Rangkuman Berita"
DATELINE_EDITION = "{tanggal} · ±5 menit baca"
DATELINE_FULL = "{tanggal} · edisi lengkap"
SIXTY_SECONDS = "Hari Ini dalam 60 Detik"
TOP_STORIES = "Berita Utama"
AT_A_GLANCE = "Sekilas"
WHY_IT_MATTERS = "Mengapa penting:"
REPORTED_BY = "Diberitakan {n} portal"
READ_AT = "Baca di {outlet} →"
RELATED = "Artikel terkait:"
MORE_IN_SECTION = "…dan {n} berita lainnya di bagian ini."   # full digest only
FOOTER = ("Disarikan dari {articles} artikel di {outlets} portal. "
          "Ringkasan ditulis AI dan bisa keliru; cek artikel aslinya untuk detail.")
FOOTER_FULL_EDITION = "Edisi lengkap memuat {n} berita."     # the edition's pointer to the archive
DEGRADED = "Sebagian ringkasan tidak tersedia hari ini. {n} berita hanya ditampilkan judulnya."
# The edition shows no story without a summary (its headline is a portal's, unchecked, and the
# editor never saw it), so its notice says where those stories are instead.
DEGRADED_EDITION = "Sebagian ringkasan tidak tersedia hari ini; {n} berita hanya ada di edisi lengkap."
EMPTY_DAY = ("Tidak ada berita yang terkumpul untuk {tanggal}. "
             "Ini biasanya tanda gangguan pengumpulan, bukan hari tanpa berita.")

# Telegram (OPS-43)
MESSAGE_HEADER = "{title} · {tanggal} (±5 menit)"
MESSAGE_OPEN_PDF = "Buka PDF untuk {n} berita utama dan sekilas lainnya."
MESSAGE_NO_PDF = "PDF tidak tersedia hari ini."
MESSAGE_NO_EDITION = "Edisi 5 menit tidak tersedia hari ini; terlampir edisi lengkapnya."
CAPTION = "{title} · {tanggal}"


def footer(articles: int, outlets: int) -> str:
    return FOOTER.format(articles=angka(articles), outlets=angka(outlets))


def degraded(n: int) -> str:
    return DEGRADED.format(n=angka(n))


def degraded_edition(n: int) -> str:
    return DEGRADED_EDITION.format(n=angka(n))


def empty_day(d: date) -> str:
    return EMPTY_DAY.format(tanggal=tanggal(d))


def caption(d: date) -> str:
    return CAPTION.format(title=TITLE, tanggal=tanggal_pendek(d))
