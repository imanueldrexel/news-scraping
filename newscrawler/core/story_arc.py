"""A top story told as an arc: today's change, how it got here, what is scheduled next (SYS-148 #338, ADR-016).

The edition's 3-4 top stories (SYS-149) are written as pure prose (owner decision,
2026-10-13: no labels) from two inputs: today's articles of the story, and the
timeline `thread_finder` found in NEWS_L1 (SYS-147). The timeline is retrieved
wide on purpose, so the model decides which items belong to the story (`alur`)
and code checks what it wrote. The answer is JSON:

    judul      <= 10 words asked (12 accepted), what changed today
    hari_ini   <= 60 words, today first
    latar      <= 70 words, the back-story from the `alur` items, every past fact dated;
               with no `alur`: why it matters (only impacts the articles state), or ""
    agenda     <= 20 words, only a scheduled or announced next step an article states, or ""
    sekilas    <= 15 words, the one-line form
    terkait / tidak_terkait   today's articles (0..n-1) about the one event / about another
    alur       the timeline items used (n..n+m-1)

`parse` refuses an answer ("json", "length", "number", "date", "subject", "alur"):
- number: every number in the prose is in today's `terkait` articles or the
  chosen `alur` items (by value, `source_check`);
- date: every date written (24/9, 24 September) is today's, a chosen item's own
  date, or one an article states -- never an unchosen item's; with no `alur`,
  `latar` holds no date but today's;
- subject: a `terkait` article names the story's subject (SYS-80);
- alur: a chosen item shares at least ALUR_MIN_EVENT_WORDS *event* words --
  content words that are not names, which say what happened rather than who
  (`story_words`, as the echo guard SYS-86) -- with today's story (judul,
  hari_ini and the `terkait` articles' text). The probe's karhutla timeline also
  held "Prabowo Lantik Wantimpres": it shares only names (Prabowo, Istana); the
  "209 Ha Lahan Masih Terbakar" report shares "lahan".
On the retry (`lenient`) off-subject articles and items are moved out instead of
refused, and the number and date checks then hold the prose to what is left.
An agenda with no date, number or scheduling word is dropped, not refused.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.llm_json import Rejected, ask_json, json_object
from newscrawler.core.source_check import dates_in, off_subject, unsupported_number, without_dates
from newscrawler.core.story_summary import article_text, guard_text, words
from newscrawler.core.summarizer import SummarizerError
from newscrawler.core.thread_finder import TimelineItem

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

LIMITS = {"judul": 12, "hari_ini": 60, "latar": 70, "agenda": 20, "sekilas": 15}
REASONS = ("json", "length", "number", "date", "subject", "alur")
ALUR_MIN_EVENT_WORDS = 1
# What makes an agenda a scheduled step rather than a guess (with a date or a number it is one already).
_SCHEDULED = re.compile(r"\b(?:dijadwalkan|jadwal|rapat|sidang|tenggat|batas waktu|berlaku|mulai|pekan depan|"
                        r"bulan depan|tahun depan|besok|lusa|rdg|pelantikan|peluncuran|pengumuman|rilis|akan)\b",
                        re.IGNORECASE)

# The example is from 2026-10-02, outside the replay set (2026-10-08..10-12) and never the day written.
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
    "- Setiap fakta dari LINI MASA ditulis dengan tanggalnya, mis. \"Pada 24/9, ...\".\n"
    "- Proyeksi, klaim, dan pendapat selalu diberi sumber. Jangan menyajikan proyeksi sebagai fakta.\n"
    "- Salin angka persis seperti di teks. Jangan membulatkan, menjumlahkan, atau menghitung selisih\n"
    "  sendiri: tulis angka yang tertulis saja.\n"
    "- Rp tanpa spasi (Rp2.574.000), tanggal hari ini sebagai \"Senin (12/10)\", kode saham sekali dalam\n"
    "  kurung: Telkom (TLKM).\n"
    "- Jangan menulis fakta yang sama dua kali.\n"
    "\n"
    "Balas HANYA dengan JSON valid, tanpa teks lain:\n"
    "{{\"judul\": \"...\", \"hari_ini\": \"...\", \"latar\": \"...\", \"agenda\": \"...\", \"sekilas\": \"...\",\n"
    "  \"terkait\": [0, 1], \"tidak_terkait\": [2], \"alur\": [3, 5, 8]}}\n"
    "\n"
    "- judul: maks 10 kata. Apa yang berubah hari ini. Bukan salinan judul portal.\n"
    "- hari_ini: 2-3 kalimat, maks 60 kata: apa yang terjadi hari ini, siapa, angka terpenting, dan\n"
    "  bila ada satu kaitan terpenting dengan alur.\n"
    "- latar: 2-3 kalimat, maks 70 kata.\n"
    "  - Jika \"alur\" berisi cuplikan: ceritakan bagaimana peristiwa sampai ke hari ini, urut waktu,\n"
    "    hanya dari cuplikan di \"alur\", setiap fakta bertanggal.\n"
    "  - Jika \"alur\" kosong: tulis mengapa peristiwa ini penting, HANYA dampak yang disebut artikel atau\n"
    "    narasumbernya; \"\" jika tidak ada.\n"
    "  - Jika alur berjalan lebih dari beberapa hari, katakan sejak kapan persoalan ini berjalan.\n"
    "- agenda: maks 20 kata. HANYA langkah berikutnya yang terjadwal atau sudah diumumkan dan tertulis\n"
    "  di teks (tanggal rapat, tenggat, berlakunya aturan), dengan sumbernya. \"\" jika tidak ada.\n"
    "  Jangan menebak.\n"
    "- sekilas: 1 kalimat, maks 15 kata.\n"
    "- alur: nomor cuplikan LINI MASA yang kamu pakai. Semua fakta di \"latar\" harus berasal dari\n"
    "  cuplikan ini.\n"
    "Batas kata di atas mutlak: jawaban yang melebihinya ditolak.\n"
    "\n"
    "CONTOH JAWABAN (dari hari lain; hanya bentuknya yang dicontoh, jangan pakai faktanya)\n"
    "{{\"judul\": \"IHSG turun 3,28% sepekan, koreksi dua pekan beruntun\",\n"
    "  \"hari_ini\": \"IHSG terkoreksi 3,28% dalam sepekan hingga Jumat (2/10). Analis meminta investor\n"
    "  mewaspadai tekanan dari kenaikan yield US Treasury.\",\n"
    "  \"latar\": \"Koreksi ini berlanjut sejak akhir September. Pada 27/9, IHSG tercatat turun 3,09% dalam\n"
    "  sepekan, dan pada 30/9 analis memperkirakan indeks rawan melemah lagi.\",\n"
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
    def prose(self) -> str:
        """The story's text as a reader sees it: today, then the back-story with the agenda closing it."""
        tail = " ".join(t for t in (self.latar, self.agenda) if t)
        return "\n\n".join(t for t in (self.hari_ini, tail) if t)


def timeline_text(item: TimelineItem) -> str:
    """What the model reads of a timeline item: its day, outlet, headline, opening."""
    d = item.day
    return (f"{copy.DAYS[d.weekday()]}, {d.day} {copy.MONTHS_SHORT[d.month - 1]} · {copy.outlet(item.source)} — "
            f"{item.headline}\n{item.opening}")


def item_source(item: TimelineItem) -> str:
    """What the guards read of a timeline item: its headline and opening -- no outlet name (SYS-87).
    Its own date is passed to the check separately (`parse`)."""
    return f"{item.headline}\n{item.opening}"


def build_prompt(shown: Sequence[dict], timeline: Sequence[TimelineItem], digest_date: date) -> str:
    n = len(shown)
    articles = "\n\n".join(f"[{i}] {article_text(a)}" for i, a in enumerate(shown))
    lines = "\n\n".join(f"[{n + k}] {timeline_text(t)}" for k, t in enumerate(timeline)) or "(kosong)"
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


def _agenda_kept(agenda: str) -> bool:
    return bool(agenda) and bool(dates_in(agenda) or re.search(r"\d", agenda) or _SCHEDULED.search(agenda))


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
    problems = [f"{key} {words(value)} kata, maks {LIMITS[key]} -- persingkat: \"{value}\""
                for key, value in fields if words(value) > LIMITS[key]]
    if problems:
        raise Rejected("length", "; ".join(problems))

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

    # Today's date and each chosen item's own date are right whether or not a text states them; they
    # are passed as dates, so their digits never make a bare number "stated" (24/9 does not license "24").
    known = {(digest_date.day, digest_date.month)} | {(t.day.day, t.day.month) for t in chosen.values()}
    source = "\n\n".join([shown_texts[i] for i in terkait] + [item_source(t) for t in chosen.values()])
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
    if not chosen:
        own = (digest_date.day, digest_date.month)
        stray_dates = [d for d in dates_in(latar) if d != own]
        if stray_dates:
            dates.append(f'latar menyebut tanggal {stray_dates[0][0]}/{stray_dates[0][1]} tanpa cuplikan alur: '
                         "tanpa alur, latar hanya boleh berisi mengapa peristiwa ini penting")
    problems = numbers + dates
    problems += [f'artikel [{i}] tidak menyebut {", ".join(anchors)}: jika membahas peristiwa lain, pindahkan ke '
                 f'"tidak_terkait" dan jangan memakai faktanya' for i in strays]
    problems += [f"cuplikan [{i}] bukan bagian dari alur peristiwa ini (\"{timeline[i - n].headline[:60]}\"): "
                 "keluarkan dari alur dan jangan memakai faktanya" for i in off]
    if problems:
        reason = "number" if numbers else "date" if dates else "subject" if strays else "alur"
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
