"""A top story told as an arc: today's change, how it got here, what is scheduled next (SYS-148 #338, ADR-016).

The edition's 3-4 top stories (SYS-149) are written as pure prose (owner decision,
2026-10-13: no labels) from two inputs: today's articles of the story, and the
timeline `thread_finder` found in NEWS_L1 (SYS-147). The timeline is retrieved
wide on purpose, so the model decides which items belong to the story (`alur`)
and code checks what it wrote. The answer is JSON:

    judul      <= 10 words asked (12 accepted), what changed today
    hari_ini   <= 60 words, today first
    latar      <= 60 words asked (70 accepted: the frame sentence made the 10-11 re-run's run 77-84),
               the back-story from the `alur` items, told as a story (SYS-154):
               a frame sentence first, at most two turning points, relative time;
               with no `alur`: why it matters (only impacts the articles state), or ""
    agenda     <= 20 words, only a scheduled or announced next step an article states, or ""
    sekilas    <= 15 words, the one-line form
    terkait / tidak_terkait   today's articles (0..n-1) about the one event / about another
    alur       the timeline items used (n..n+m-1)

`parse` refuses an answer ("json", "length", "style", "number", "date", "subject", "alur"):
- style: the latar reads as a chronicle (`arc_style`, SYS-156): more than
  MAX_LATAR_DATES calendar dates, more than MAX_LATAR_ANCHORS time anchors (dates and
  relative times not after "sejak", SYS-164), more than MAX_DATE_OPENINGS sentences opening
  on a time anchor, or two sentences opening on the same word; or, with `alur`, its first
  sentence is not tied to today (SYS-159). The 2026-10-08..12 replay: 69% of latar
  sentences were "Pada d/m, ...";
- number: every number in the prose is in today's `terkait` articles or the
  chosen `alur` items (by value, `source_check`); an ordinal or series claim
  ("gelombang kedua", "tiga hari beruntun") counts no more than the chosen
  items allow, unless a source states it, and a record ("terendah sejak ...")
  only when a source states it (SYS-158); "bertambah/naik/turun menjadi N" (or "hingga N", "ke
  angka N", SYS-170) only when a source states N as a total or a change (SYS-161);
- date: every date written (24/9, 24 September) is today's, a chosen item's own
  date, or one an article states -- never an unchosen item's; every relative
  time ("awal Oktober", "pekan lalu") spans one of those or is stated in today's articles
  (SYS-157/162: a timeline item's "kemarin" was written from another day); every future time
  ("besok", "minggu depan", "akhir tahun ini") is one today's articles state, compared by key
  ("minggu depan" = "pekan depan"), never a stated date retold as a relative time (SYS-169);
  with no `alur`, `latar` holds no date but today's;
- subject: a `terkait` article names the story's subject (SYS-80);
- alur: a chosen item shares at least ALUR_MIN_EVENT_WORDS *event* words --
  content words that are not names, which say what happened rather than who
  (`story_words`, as the echo guard SYS-86) -- with today's story (judul,
  hari_ini and the `terkait` articles' text). The probe's karhutla timeline also
  held "Prabowo Lantik Wantimpres": it shares only names (Prabowo, Istana); the
  "209 Ha Lahan Masih Terbakar" report shares "lahan".
On the retry (`lenient`) off-subject articles and items are moved out instead of
refused, and the number and date checks then hold the prose to what is left.
An agenda with no date, number or scheduling word is dropped, not refused; so is one that
repeats the latar or hari_ini (SYS-163: its date -- or since SYS-165 its future time,
"minggu depan" -- and at least AGENDA_REPEAT_SHARE of its content words are there).
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence

from newscrawler.core import arc_style
from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.llm_json import Rejected, ask_json, json_object
from newscrawler.core.source_check import (dates_in, future_phrases, future_times, off_subject, ordinal_claims,
                                           relative_name, relative_times, resolve, stated_claims, unbacked_changes,
                                           unstated_future_times, unsupported_number, without_dates)
from newscrawler.core.story_summary import article_text, guard_text, words
from newscrawler.core.summarizer import SummarizerError
from newscrawler.core.thread_finder import TimelineItem

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

LIMITS = {"judul": 12, "hari_ini": 60, "latar": 70, "agenda": 20, "sekilas": 15}     # accepted
ASKED = {**LIMITS, "judul": 10, "latar": 60}                                            # what PROMPT asks
REASONS = ("json", "length", "style", "number", "date", "subject", "alur")
ALUR_MIN_EVENT_WORDS = 1
MAX_LATAR_DATES = 2     # SYS-156: calendar dates in a latar (13 of 19 replayed latar held >= 3)
# SYS-156: sentences of a latar that open on a date ("Pada 24/9, ...") or, since SYS-164, a relative time
# ("Pekan lalu, ..."). A date inside a sentence is held only by the counts: the 10-12 re-run refused
# "..., ditutup menguat 1,04% pada Jumat (9/10)".
MAX_DATE_OPENINGS = 1
# SYS-164: dates and relative times (not "sejak ...") in a latar: a frame and two turning points fit. The v5
# Karhutla latar told all four chosen items in order with four (Pekan lalu, 5/10, 8/10, Kemarin).
MAX_LATAR_ANCHORS = 3
AGENDA_REPEAT_SHARE = 0.5   # SYS-163: El-Sisi 10-10 repeated 7 of its 9 content words from the latar
STYLE_ASK = ("tulis latar sebagai cerita: satu kalimat bingkai dan paling banyak dua titik balik, dikaitkan "
             "dengan peristiwa hari ini, dengan waktu relatif (\"awal Oktober\", \"pekan lalu\")")
# What makes an agenda a scheduled step rather than a guess (with a date or a number it is one already).
_SCHEDULED = re.compile(r"\b(?:dijadwalkan|jadwal|rapat|sidang|tenggat|batas waktu|berlaku|mulai|rdg|pelantikan|"
                        r"peluncuran|pengumuman|rilis|akan)\b", re.IGNORECASE)

# The example is from 2026-10-02, outside the replay set (2026-10-08..10-12) and never the day written. Its
# facts are that day's (KONTAN: 3,28% sepekan, +0,46% to 6.036,89 after six days down) and its two items' (KONTAN
# 27/9: 3,09% sepekan; 1/10: 5.973 intraday). SYS-155: its latar is a story -- a frame, two turning points, no
# calendar date -- because the model copies the example's shape more reliably than the rules.
PROMPT = (
    "Kamu redaktur briefing berita harian berbahasa Indonesia. Tugasmu menceritakan SATU berita utama\n"
    "hari ini sebagai alur: apa yang terjadi hari ini, bagaimana sampai ke sini, dan agenda berikutnya\n"
    "bila ada. Pembacamu cerdas tetapi sibuk dan membaca di ponsel.\n"
    "\n"
    "Di bawah ada dua bagian:\n"
    "- HARI INI: {n} artikel {tanggal} yang dikelompokkan mesin sebagai satu berita. Pengelompokan ini\n"
    "  bisa salah.\n"
    "- LINI MASA: {m} cuplikan berita bertanggal dari 30 hari sebelumnya, dicari mesin karena MIRIP.\n"
    "  Mirip belum tentu satu alur.\n"
    "\n"
    "LANGKAH\n"
    "1. Tentukan SATU peristiwa hari ini yang dibahas paling banyak artikel HARI INI. Nomor artikel yang\n"
    "   membahas peristiwa lain masukkan ke \"tidak_terkait\".\n"
    "2. Dari LINI MASA, pilih HANYA cuplikan yang merupakan tahap sebelumnya dari peristiwa yang sama:\n"
    "   yang memicu, mendahului, atau menjadi langkah sebelumnya. Berita lain yang hanya bertopik mirip\n"
    "   (harga lain, tokoh yang sama di urusan lain, wilayah yang sama) BUKAN alur. Untuk berita harian\n"
    "   yang berulang (penutupan IHSG, harga emas), pilih hanya titik balik, bukan setiap hari.\n"
    "   Jika tidak ada yang cocok, \"alur\" kosong.\n"
    "3. Tulis hanya dari teks di bawah. Jangan menambah fakta, angka, nama, jabatan, tanggal, sebab,\n"
    "   atau dampak yang tidak tertulis.\n"
    "\n"
    "ATURAN TULISAN\n"
    "- Tulis sebagai cerita pendek yang mengalir: paragraf dengan kalimat yang bersambung, tanpa\n"
    "  daftar, tanpa label, tanpa poin. Bahasa Indonesia baku, kalimat aktif, tanpa clickbait, tanpa\n"
    "  tanda seru, tanpa pertanyaan retoris.\n"
    "- Mulai dari yang BARU hari ini. Latar datang sesudahnya.\n"
    "- Kata sebab-akibat (\"karena\", \"akibat\", \"dipicu\", \"memicu\", \"sehingga\", \"imbas\") HANYA boleh\n"
    "  dipakai jika hubungan itu tertulis di teks, dan sebutkan siapa yang mengatakannya: \"yang menurut\n"
    "  analis Phintraco Sekuritas dipicu ...\". Kata urutan waktu (\"sebelumnya\", \"sejak\", \"sepekan\n"
    "  kemudian\") boleh dipakai tanpa sumber.\n"
    "- Setiap fakta dari LINI MASA harus berasal dari cuplikannya.\n"
    "- Klaim urutan (\"gelombang kedua\", \"untuk ketiga kalinya\", \"tiga hari beruntun\") hanya jika\n"
    "  cuplikan alur yang kamu pilih cukup untuk menghitungnya, atau klaim itu tertulis di teks.\n"
    "  \"Pertama kali sejak\", \"terendah sejak\", \"tertinggi sejak\" hanya jika tertulis di teks.\n"
    "- Proyeksi, klaim, dan pendapat selalu diberi sumber. Jangan menyajikan proyeksi sebagai fakta.\n"
    "- Salin angka persis seperti di teks. Jangan membulatkan, menjumlahkan, atau menghitung selisih\n"
    "  sendiri: tulis angka yang tertulis saja.\n"
    "- Rp tanpa spasi (Rp2.574.000), tanggal hari ini di hari_ini sebagai \"Senin (12/10)\", kode saham\n"
    "  sekali dalam kurung: Telkom (TLKM).\n"
    "- Jangan menulis fakta yang sama dua kali.\n"
    "\n"
    "Balas HANYA dengan JSON valid, tanpa teks lain:\n"
    "{{\"judul\": \"...\", \"hari_ini\": \"...\", \"latar\": \"...\", \"agenda\": \"...\", \"sekilas\": \"...\",\n"
    "  \"terkait\": [0, 1], \"tidak_terkait\": [2], \"alur\": [3, 5, 8]}}\n"
    "\n"
    "- judul: maks 10 kata. Apa yang berubah hari ini. Bukan salinan judul portal.\n"
    "- hari_ini: 2-3 kalimat, maks 60 kata: apa yang terjadi hari ini, siapa, angka terpenting, dan\n"
    "  bila ada satu kaitan terpenting dengan alur.\n"
    "- latar: 2-3 kalimat, maks 60 kata.\n"
    "  - Jika \"alur\" berisi cuplikan, latar adalah cerita, bukan catatan harian:\n"
    "    1. Kalimat pertama adalah bingkai: apa arti peristiwa sebelumnya bagi berita hari ini (lanjutan,\n"
    "       gelombang berikutnya, makin parah, atau berbalik arah), dengan menyebut peristiwa atau\n"
    "       pelaku hari ini. Jangan membuka latar dengan tanggal. Jika alur berjalan lebih dari\n"
    "       beberapa hari, katakan sejak kapan, mis. \"sejak akhir September\".\n"
    "    2. Pilih paling banyak dua titik balik, yaitu yang mengubah keadaan. Lewati tahap proses\n"
    "       (\"dibahas\", \"disebut\", \"dikabarkan\", \"ditanggapi\") kecuali itulah titik baliknya.\n"
    "    3. Kaitkan setiap fakta lampau dengan hari ini (\"kini\", \"kali ini\", \"setelah\", \"menyusul\",\n"
    "       \"berbeda dengan\"), bukan sekadar urutan waktu (\"lalu\", \"kemudian\"). Tulis angka hari ini\n"
    "       sebagai lanjutan angka lampau (\"bertambah/naik/turun menjadi N\", \"... hingga N\", \"... ke\n"
    "       angka N\") HANYA jika artikel menyebut N\n"
    "       sebagai total berjalan atau perubahan (\"hingga September\", \"sepanjang tahun\", \"naik dari\");\n"
    "       \"total ada N\" saja hanya jumlah peristiwa itu sendiri.\n"
    "       Jika tidak, keduanya peristiwa terpisah: ceritakan angka hari ini sebagai peristiwa hari ini.\n"
    "    4. Tulis waktu cuplikan dengan waktu relatif yang tertera dalam kurung di LINI MASA, mis.\n"
    "       \"akhir September\", \"pekan lalu\", \"kemarin\", bukan \"Kamis (8/10)\" atau \"Pada 24/9\".\n"
    "       Tanggal kalender hanya jika tanggal itu sendiri penting (tenggat, sidang, pemungutan\n"
    "       suara), paling banyak dua di latar. Seluruh latar paling banyak tiga penanda waktu\n"
    "       (tanggal atau waktu relatif; \"sejak ...\" tidak dihitung).\n"
    "    5. Jangan membuka dua kalimat dengan kata yang sama.\n"
    "    6. Akhiri dengan apa yang masih terbuka (siapa yang memutuskan berikutnya, apa yang masih\n"
    "       diperdebatkan) HANYA jika artikel menyebutnya. Jika tidak, berhenti.\n"
    "  - Jika \"alur\" kosong: tulis mengapa peristiwa ini penting, HANYA dampak yang disebut artikel atau\n"
    "    narasumbernya; \"\" jika tidak ada.\n"
    "- agenda: maks 20 kata. HANYA langkah berikutnya yang terjadwal atau sudah diumumkan dan tertulis\n"
    "  di teks (tanggal rapat, tenggat, berlakunya aturan), dengan sumbernya. \"\" jika tidak ada.\n"
    "  Jangan menebak. Tulis waktunya seperti tertulis di artikel HARI INI (\"Kamis (15/10)\", \"pekan\n"
    "  depan\"); jangan mengubah tanggal menjadi \"besok\" atau \"pekan ini\".\n"
    "- sekilas: 1 kalimat, maks 15 kata.\n"
    "- alur: nomor cuplikan LINI MASA yang kamu pakai. Semua fakta di \"latar\" harus berasal dari\n"
    "  cuplikan ini.\n"
    "Batas kata di atas mutlak: jawaban yang melebihinya ditolak.\n"
    "\n"
    "CONTOH JAWABAN (dari hari lain; hanya bentuknya yang dicontoh, jangan pakai faktanya)\n"
    "{{\"judul\": \"IHSG turun 3,28% sepekan, koreksi dua pekan beruntun\",\n"
    "  \"hari_ini\": \"IHSG terkoreksi 3,28% dalam sepekan meski ditutup menguat 0,46% ke 6.036,89 pada\n"
    "  Jumat (2/10). Analis meminta investor mewaspadai tekanan dari kenaikan yield US Treasury.\",\n"
    "  \"latar\": \"Ini pekan kedua beruntun IHSG ditutup merah. Pekan sebelumnya indeks sudah turun\n"
    "  3,09%, dan penguatan Jumat ini memutus pelemahan enam hari beruntun yang kemarin sempat membawa\n"
    "  IHSG ke 5.973.\",\n"
    "  \"agenda\": \"\", \"sekilas\": \"IHSG turun 3,28% sepekan, koreksi pekan kedua beruntun.\",\n"
    "  \"terkait\": [0, 1], \"tidak_terkait\": [2], \"alur\": [4, 6]}}\n"
    "\n"
    "HARI INI\n"
    "{articles}\n"
    "\n"
    "LINI MASA\n"
    "{timeline}"
)


@dataclass(frozen=True)
class StoryArc:
    judul: str
    hari_ini: str
    latar: str
    agenda: str
    sekilas: str
    terkait: List[int]                  # today's shown articles about the event
    tidak_terkait: List[int]
    alur: List[int]                     # positions in the timeline (0..m-1), oldest first
    alur_items: List[TimelineItem] = field(default_factory=list)
    demoted: int = 0                    # today's articles moved out on the retry (SYS-80)
    demoted_alur: int = 0               # timeline items moved out on the retry
    agenda_dropped: bool = False

    @property
    def back_story(self) -> str:
        """The second paragraph as a reader sees it: the latar, closed by the agenda."""
        return " ".join(t for t in (self.latar, self.agenda) if t)

    @property
    def prose(self) -> str:
        """The story's text as a reader sees it: today, then the back-story."""
        return "\n\n".join(t for t in (self.hari_ini, self.back_story) if t)


def timeline_text(item: TimelineItem, digest_date: date) -> str:
    """What the model reads of a timeline item: its day with the relative phrase to write for it
    (SYS-154: the 10-11/10-12 re-run still dated every past fact "Kamis (8/10)"), outlet, headline, opening."""
    d = item.day
    return (f"{copy.DAYS[d.weekday()]}, {d.day} {copy.MONTHS_SHORT[d.month - 1]} ({relative_name(d, digest_date)}) · "
            f"{copy.outlet(item.source)} — {item.headline}\n{item.opening}")


def item_source(item: TimelineItem) -> str:
    """What the guards read of a timeline item: its headline and opening -- no outlet name (SYS-87).
    Its own date is passed to the check separately (`parse`)."""
    return f"{item.headline}\n{item.opening}"


def build_prompt(shown: Sequence[dict], timeline: Sequence[TimelineItem], digest_date: date) -> str:
    n = len(shown)
    articles = "\n\n".join(f"[{i}] {article_text(a)}" for i, a in enumerate(shown))
    lines = "\n\n".join(f"[{n + k}] {timeline_text(t, digest_date)}" for k, t in enumerate(timeline)) or "(kosong)"
    return PROMPT.format(n=n, m=len(timeline), tanggal=copy.tanggal(digest_date), articles=articles, timeline=lines)


def _text(data: dict, key: str, required: bool) -> str:
    value = data.get(key)
    if value is None and not required:
        value = ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise Rejected("json", f'"{key}" harus teks yang tidak kosong' if required else f'"{key}" harus teks')
    return " ".join(value.split())


def _indexes(data: dict, key: str, lo: int, hi: int, what: str) -> List[int]:
    value = data.get(key)
    if value is None and key in ("tidak_terkait", "alur"):
        value = []
    if not isinstance(value, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in value):
        raise Rejected("json", f'"{key}" harus daftar nomor {what}')
    if any(not lo <= i < hi for i in value):
        raise Rejected("json", f'"{key}" memuat nomor yang bukan {what} ({lo}-{hi - 1})' if hi > lo
                       else f'"{key}" harus kosong: tidak ada {what}')
    if len(set(value)) != len(value):
        raise Rejected("json", f'"{key}" memuat nomor yang sama dua kali')
    return value


def _events(words: dict) -> set:
    return {w for w, is_name in words.items() if not is_name}


def off_thread(judul: str, hari_ini: str, related: Sequence[str], items: dict) -> List[int]:
    """The chosen timeline items (`items`: index -> item) that share fewer than
    ALUR_MIN_EVENT_WORDS event words with today's story: the judul, hari_ini and
    `related` (the terkait articles' guard texts; their headline lines are left
    out, as a Title Case headline's capitals say nothing about names)."""
    bodies = " ".join(text.partition("\n")[2] for text in related)
    story = _events(story_words.story_content_words(judul, f"{hari_ini} {bodies}"))
    return [i for i, item in items.items()
            if len(story & _events(story_words.story_content_words(item.headline, item.opening)))
            < ALUR_MIN_EVENT_WORDS]


def chronicle(latar: str, judul: str, hari_ini: str, has_alur: bool) -> List[str]:
    """SYS-156/SYS-159: what makes `latar` read as a chronicle rather than a story, one line per rule
    broken (empty when it reads as a story). The tie to today is asked only of a latar with `alur`:
    without one, the latar says why the news matters."""
    problems = []
    dates = len(dates_in(latar))
    if dates > MAX_LATAR_DATES:
        problems.append(f"latar memuat {dates} tanggal kalender, maks {MAX_LATAR_DATES}")
    anchors = arc_style.time_anchors(latar)
    if len(anchors) > MAX_LATAR_ANCHORS:
        quoted = ", ".join(f'"{a}"' for a in anchors)
        problems.append(f"latar memuat {len(anchors)} penanda waktu ({quoted}), maks {MAX_LATAR_ANCHORS}: "
                        "ceritakan paling banyak dua titik balik")
    opened = [s for s in arc_style.sentences(latar) if arc_style.opens_on_time(s)]
    if len(opened) > MAX_DATE_OPENINGS:
        quoted = ", ".join(f'"{" ".join(s.split()[:8])} ..."' for s in opened)
        problems.append(f"{len(opened)} kalimat latar dibuka dengan tanggal atau waktu ({quoted}), "
                        f"maks {MAX_DATE_OPENINGS}")
    word = arc_style.repeated_opening(latar)
    if word:
        problems.append(f"dua kalimat latar dibuka dengan kata \"{word}\"")
    if has_alur and not arc_style.tied_to_today(latar, judul, hari_ini):
        problems.append("kalimat pertama latar tidak mengaitkan alur dengan peristiwa hari ini")
    return problems


def _backing_days(known: set, last: date, digest_date: date, schedule: bool) -> set:
    """SYS-174 (#373): the `known` days that may back a span ending on `last`. Today backs only a span that has
    ended: while one still runs ("akhir bulan" from the 21st) today sits inside it whether the phrase tells a past
    event or an invented schedule. A past day inside it backs the past reading (the 10-08 arcs' "awal Oktober" for a
    6/10 item), except in the agenda, the scheduled step, where only a day after today does ("Rabu (28/10)")."""
    if last <= digest_date:
        return known
    return {d for d in known if d > digest_date} if schedule else known - {digest_date}


def unbacked_times(text: str, digest_date: date, known: set, stated: str, schedule: bool = False) -> List[str]:
    """SYS-157: the relative time phrases of `text` ("awal Oktober", "pekan lalu") whose days hold
    none of the `known` dates (today, the chosen items' own dates, the dates the sources state) and
    that `stated` -- today's `terkait` articles only -- does not state as written. A phrase means
    something only from the day it was written: a 23/9 item's "kemarin" is 22/9 (SYS-162). A future time
    ("akhir bulan ini") is not read here: `unstated_future_times` judges it by key, never by its span (SYS-169).
    A span still running past today is not backed by today, nor in a `schedule` (the agenda) by a past day
    (`_backing_days`, SYS-174)."""
    stated = " ".join(stated.lower().split())
    return [phrase for phrase, first, last in relative_times(text, digest_date)
            if not future_phrases(phrase)
            and not any(first <= d <= last for d in _backing_days(known, last, digest_date, schedule))
            and " ".join(phrase.lower().split()) not in stated]


def overcounted(text: str, items: int, stated: set) -> List[str]:
    """SYS-158: the ordinal and series claims of `text` that the chosen timeline does not back -- a
    count N needs N-1 earlier items, a record ("terendah sejak") cannot be counted at all -- and
    that no source states (`stated`: the sources' claim keys)."""
    return [claim for claim, n, key in ordinal_claims(text)
            if key not in stated and (n is None or n - 1 > items)]


def _agenda_kept(agenda: str) -> bool:
    """A future time (`source_check.future_phrases`) makes the agenda a scheduled step, like a date (SYS-166)."""
    return bool(agenda) and bool(dates_in(agenda) or re.search(r"\d", agenda) or _SCHEDULED.search(agenda)
                                 or future_phrases(agenda))


def agenda_repeats(agenda: str, latar: str, hari_ini: str) -> bool:
    """SYS-163: the agenda tells a time the latar or hari_ini already tells -- a date, or since
    SYS-165 a future time ("minggu depan") -- with at least AGENDA_REPEAT_SHARE of its content words
    there too (2026-10-10: "Minggu (11/10) pukul 10.30 WIB, Prabowo menerima El-Sisi di Istana ..."
    closed a latar that had just said it; 2026-10-12: "Pelantikan pimpinan BPGMN diharapkan
    dilakukan minggu depan" closed a story whose hari_ini had just said it). Dropped, not refused:
    it adds nothing, so a retry would buy the reader nothing."""
    told = f"{latar} {hari_ini}"
    if not (set(dates_in(agenda)) & set(dates_in(told)) or future_times(agenda) & future_times(told)):
        return False
    words, seen = story_words.content_words(agenda), story_words.content_words(told)
    return bool(words) and sum(w in seen for w in words) >= AGENDA_REPEAT_SHARE * len(words)


def parse(answer: Optional[str], shown_texts: Sequence[str], timeline: Sequence[TimelineItem], digest_date: date,
          lenient: bool = False) -> StoryArc:
    """The answer as a StoryArc, or Rejected (module docstring). `shown_texts`
    are today's articles' `guard_text`s, in prompt order; `lenient` is the retry."""
    n, m = len(shown_texts), len(timeline)
    data = json_object(answer)
    judul, hari_ini, sekilas = _text(data, "judul", True), _text(data, "hari_ini", True), _text(data, "sekilas", True)
    latar, agenda = _text(data, "latar", False), _text(data, "agenda", False)
    terkait = _indexes(data, "terkait", 0, n, "artikel HARI INI")
    tidak = _indexes(data, "tidak_terkait", 0, n, "artikel HARI INI")
    alur = _indexes(data, "alur", n, n + m, "cuplikan LINI MASA")
    if not terkait:
        raise Rejected("json", '"terkait" tidak boleh kosong')
    if set(terkait) & set(tidak) or len(terkait) + len(tidak) != n:
        raise Rejected("json", f"setiap nomor artikel 0-{n - 1} harus muncul tepat sekali di terkait atau tidak_terkait")

    fields = [("judul", judul), ("hari_ini", hari_ini), ("latar", latar), ("agenda", agenda), ("sekilas", sekilas)]
    # The retry names how much to cut, down to what the prompt asks: the 5-day re-run's "persingkat"
    # retries left the latar at 77 -> 77 and 87 -> 80 words.
    problems = [f"{key} {words(value)} kata, maks {LIMITS[key]} -- buang paling sedikit "
                f"{words(value) - ASKED[key]} kata{' (mis. satu kalimat)' if key == 'latar' else ''}: \"{value}\""
                for key, value in fields if words(value) > LIMITS[key]]
    if problems:
        # The one retry rewrites the latar, so it hears the style rules too (10-11 re-run: shortened,
        # then refused as style).
        style = chronicle(latar, judul, hari_ini, bool(alur))
        raise Rejected("length", "; ".join(problems + ([f"{'; '.join(style)} -- {STYLE_ASK}"] if style else [])))

    anchors, strays = off_subject(judul, hari_ini, {i: shown_texts[i] for i in terkait})
    chosen = {i: timeline[i - n] for i in alur}
    off = off_thread(judul, hari_ini, [shown_texts[i] for i in terkait], chosen)
    demoted = demoted_alur = 0
    if lenient:
        terkait, tidak, demoted, strays = [i for i in terkait if i not in strays], tidak + strays, len(strays), []
        alur, demoted_alur, off = [i for i in alur if i not in off], len(off), []
        chosen = {i: timeline[i - n] for i in alur}

    agenda_dropped = bool(agenda) and not _agenda_kept(agenda)
    if agenda_dropped:
        logger.info(f"Arc agenda dropped (no date, number or scheduled step): {agenda!r}")
        agenda = ""
    elif agenda and agenda_repeats(agenda, latar, hari_ini):
        logger.info(f"Arc agenda dropped (repeats the latar or hari_ini): {agenda!r}")
        agenda, agenda_dropped = "", True

    style = chronicle(latar, judul, hari_ini, bool(chosen))
    # Today's date and each chosen item's own date are right whether or not a text states them; they
    # are passed as dates, so their digits never make a bare number "stated" (24/9 does not license "24").
    known = {(digest_date.day, digest_date.month)} | {(t.day.day, t.day.month) for t in chosen.values()}
    source = "\n\n".join([shown_texts[i] for i in terkait] + [item_source(t) for t in chosen.values()])
    # A relative time may span any day a date check accepts (SYS-157).
    days = ({digest_date} | {t.day for t in chosen.values()}
            | {resolve(d, m, digest_date) for d, m in dates_in(source)}) - {None}
    claims = stated_claims(source)
    stated_today = "\n\n".join(shown_texts[i] for i in terkait)   # where a relative phrase may be stated
    numbers, dates = [], []
    for key, value in [("judul", judul), ("hari_ini", hari_ini), ("latar", latar), ("agenda", agenda),
                       ("sekilas", sekilas)]:
        # Numbers and dates are named apart, so the one retry hears about both.
        number = unsupported_number(without_dates(value), source)
        if number:
            numbers.append(f'angka "{number}" di {key} tidak ada di artikel atau cuplikan alur')
        bad = unsupported_number(value, source, known)
        if bad and dates_in(bad):
            dates.append(f'tanggal "{bad}" di {key} bukan tanggal hari ini, tanggal cuplikan alur yang dipilih, '
                         "atau tanggal yang tertulis di artikel")
        elif bad and not number:
            numbers.append(f'"{bad}" di {key} tidak ada di artikel atau cuplikan alur')
        numbers += [f'"{claim}" di {key} menghitung lebih dari {len(chosen)} cuplikan alur yang dipilih, atau '
                    "klaim rekor yang tidak tertulis di teks" for claim in overcounted(value, len(chosen), claims)]
        numbers += [f'"{claim}" di {key} membaca angka itu sebagai total atau perubahan, padahal artikel tidak '
                    "menyebutnya begitu: ceritakan angka hari ini sebagai peristiwa hari ini"
                    for claim in unbacked_changes(value, source)]
        dates += [f'waktu "{phrase}" di {key} tidak cocok dengan tanggal hari ini, tanggal cuplikan alur yang '
                  "dipilih, atau tanggal yang tertulis di artikel" for phrase in unbacked_times(value, digest_date,
                                                                                                days, stated_today,
                                                                                                key == "agenda")]
        dates += [f'waktu "{phrase}" di {key} tidak tertulis di artikel hari ini: tulis waktunya seperti yang '
                  "tertulis di artikel, mis. tanggalnya" for phrase in unstated_future_times(value, stated_today)]
    if not chosen:
        own = (digest_date.day, digest_date.month)
        stray_dates = [d for d in dates_in(latar) if d != own]
        if stray_dates:
            dates.append(f'latar menyebut tanggal {stray_dates[0][0]}/{stray_dates[0][1]} tanpa cuplikan alur: '
                         "tanpa alur, latar hanya boleh berisi mengapa peristiwa ini penting")
    problems = ([f"{'; '.join(style)} -- {STYLE_ASK}"] if style else []) + numbers + dates
    problems += [f'artikel [{i}] tidak menyebut {", ".join(anchors)}: jika membahas peristiwa lain, pindahkan ke '
                 f'"tidak_terkait" dan jangan memakai faktanya' for i in strays]
    problems += [f"cuplikan [{i}] bukan bagian dari alur peristiwa ini (\"{timeline[i - n].headline[:60]}\"): "
                 "keluarkan dari alur dan jangan memakai faktanya" for i in off]
    if problems:
        reason = ("style" if style else "number" if numbers else "date" if dates else "subject" if strays
                  else "alur")
        raise Rejected(reason, "; ".join(problems))
    positions = sorted(i - n for i in alur)
    return StoryArc(judul, hari_ini, latar, agenda, sekilas, terkait, tidak, positions,
                    [timeline[p] for p in positions], demoted, demoted_alur, agenda_dropped)


def write_arc(summarizer, shown: Sequence[dict], timeline: Sequence[TimelineItem], digest_date: date,
              rejections: list) -> Optional[StoryArc]:
    """Ask once, and once more with the reason (lenient: strays and off-thread
    items moved out); None after two refusals, each reason appended to
    `rejections`. Provider errors pass through (llm_json, on_error="raise")."""
    texts = [guard_text(a) for a in shown]

    def check(answer: str, attempt: int) -> StoryArc:
        return parse(answer, texts, timeline, digest_date, lenient=attempt > 0)

    try:
        outcome = ask_json(summarizer, build_prompt(shown, timeline, digest_date), check, on_error="raise",
                           label=f"Arc of {shown[0]['headline'][:80]!r}")
    except SummarizerError as e:
        rejections.extend(getattr(e, "refusals", []))
        raise
    rejections.extend(outcome.reasons)
    return outcome.value
