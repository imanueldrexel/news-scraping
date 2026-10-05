"""One story's structured summary, and the checks that make its rules hold (SYS-82 #239).

The digest used to ask for "3-5 bullets" in free text: no length limit, no way to
learn which articles the model ignored (SYS-80 #236: a headline from one event over
bullets from another), and no way to check a number. The model now answers JSON:

    judul            <= 10 words, the story's own headline (not a portal's)
    inti             <= 25 words, one sentence: what happened, who, the key number
    poin             0-2 sentences of <= 20 words, each a new fact
    mengapa_penting  <= 20 words, only an impact the articles state; "" when none
    sekilas          <= 15 words, the one-line form for the edition's Sekilas list
    terkait          indexes of the articles about the story's one event
    tidak_terkait    indexes of the articles about something else

and `parse` refuses an answer that breaks a rule: not JSON or the wrong shape
("json"), a field over its word limit ("length" -- never cut mid-sentence), or a
number that is not in the articles ("number": digit runs compared with their
separators removed, so "Rp2.574.000" matches "Rp 2.574.000" but "13,3 juta" does
not match "13.300.000"; the prompt says to copy numbers verbatim). A refused
answer is asked again once, with the reason; a second refusal is the caller's
fallback (the story's headline list).

Which articles the model sees: one per outlet first, most authoritative outlets
first, then the remaining articles, up to MAX_ARTICLES. The links and the lead
article are drawn from what it marked `terkait`; an article it did not see cannot
be judged and is kept, as the clusterer grouped it (it still counts towards the
portal count, never towards a link).
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from newscrawler.core import newsletter_copy as copy
from newscrawler.core.constants import SOURCE_AUTHORITY

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_ARTICLES = 6
ARTICLE_CHARS = 800
# The refusal thresholds. The prompt asks for the same numbers except the judul: it asks for
# "maks 10 kata" and a judul is refused only above 12 (CTO/owner decision 2026-10-05: 6 of 7
# second refusals on 2026-09-28 were a judul of 11-12 words, one of them the day's BI-rate
# story; asking for 12 would make the model aim at 12 and overshoot).
LIMITS = {"judul": 12, "inti": 25, "poin": 20, "mengapa_penting": 20, "sekilas": 15}
JUDUL_ASKED = 10
MAX_POIN = 2
REASONS = ("json", "length", "number")

# The example answer is from a past digest (2026-10-04), never from the day being summarised.
PROMPT = (
    "Kamu redaktur briefing berita harian berbahasa Indonesia. Pembaca membaca seluruh edisi dalam 5 menit\n"
    "di ponsel, jadi setiap kata harus membawa fakta.\n"
    "\n"
    "Di bawah ada {n} artikel dari portal berbeda yang dikelompokkan mesin sebagai satu berita.\n"
    "Pengelompokan ini bisa salah.\n"
    "\n"
    "LANGKAH\n"
    "1. Tentukan SATU peristiwa yang dibahas paling banyak artikel. Nomor artikel yang membahas peristiwa\n"
    "   lain masukkan ke \"tidak_terkait\".\n"
    "2. Tulis hanya dari artikel yang terkait. Jangan menambah fakta, angka, nama, jabatan, tanggal, atau\n"
    "   dampak yang tidak tertulis di artikel.\n"
    "3. Jika artikel menyebut angka berbeda untuk hal yang sama, pakai angka yang disebut paling banyak\n"
    "   artikel. Jangan menulis dua angka yang saling bertentangan.\n"
    "\n"
    "ATURAN TULISAN\n"
    "- Bahasa Indonesia baku yang lugas dan kalimat aktif, gaya kantor berita. Tanpa gaya clickbait\n"
    "  (\"Awas!\", \"Ngacir\", \"Duet Maut\"), tanpa tanda seru, tanpa pertanyaan retoris.\n"
    "- Proyeksi, klaim, dan pendapat selalu diberi sumber: \"menurut OJK\", \"kata ekonom Indef Didik J. "
    "Rachbini\".\n"
    "  Jangan menyajikan proyeksi sebagai fakta.\n"
    "- Salin angka persis seperti di artikel; jangan membulatkan atau mengubah satuan. Tulis \"Rp\" tanpa spasi\n"
    "  (Rp2.574.000), tanggal sebagai \"Jumat (2/10)\". Kode saham sekali, dalam kurung: Telkom (TLKM).\n"
    "- Setiap poin wajib memuat fakta baru (angka, keputusan, nama, waktu, atau akibat) yang belum ada di\n"
    "  \"inti\". Jangan menulis poin yang hanya berisi \"X menyampaikan/menegaskan/menilai\" tanpa isi "
    "pernyataannya.\n"
    "- Lebih baik sedikit poin daripada poin yang lemah. Nol poin boleh.\n"
    "\n"
    "Balas HANYA dengan JSON valid, tanpa teks lain:\n"
    "{{\"judul\": \"...\", \"inti\": \"...\", \"poin\": [\"...\"], \"mengapa_penting\": \"...\", "
    "\"sekilas\": \"...\",\n"
    "  \"terkait\": [0, 2], \"tidak_terkait\": [1]}}\n"
    "\n"
    "- judul: maks 10 kata. Subjek + kata kerja + fakta kunci. Bukan salinan judul portal.\n"
    "- inti: 1 kalimat, maks 25 kata: apa yang terjadi, siapa, angka terpenting.\n"
    "- poin: 0-2 kalimat, masing-masing maks 20 kata.\n"
    "- mengapa_penting: maks 20 kata, HANYA dampak yang disebut artikel atau narasumbernya; \"\" jika tidak ada.\n"
    "- sekilas: 1 kalimat, maks 15 kata, untuk daftar singkat.\n"
    "Batas kata di atas mutlak: jawaban yang melebihinya ditolak. Hitung kata setiap poin; tulis 10-18 kata.\n"
    "\n"
    "CONTOH JAWABAN\n"
    "{{\"judul\": \"Harga emas Antam bertahan di Rp2.574.000 per gram\",\n"
    "  \"inti\": \"Harga emas batangan Antam tidak berubah pada Minggu (4/10) di Rp2.574.000 per gram.\",\n"
    "  \"poin\": [\"Harga buyback juga tetap di Rp2.380.000 per gram, selisih Rp194.000 dari harga jual.\"],\n"
    "  \"mengapa_penting\": \"\", \"sekilas\": \"Emas Antam stagnan di Rp2.574.000 per gram pada Minggu (4/10).\",\n"
    "  \"terkait\": [0, 2], \"tidak_terkait\": [1]}}\n"
    "\n"
    "ARTIKEL\n"
    "{articles}"
)

RETRY = "\n\nJawaban sebelumnya ditolak: {detail}. Perbaiki dan balas HANYA dengan JSON valid."


class Rejected(Exception):
    """An answer that breaks a rule. `reason` is one of REASONS; `detail` is the
    one line the retry tells the model."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class StorySummary:
    judul: str
    inti: str
    poin: List[str]
    mengapa_penting: str
    sekilas: str
    terkait: List[int]
    tidak_terkait: List[int]
    dropped_poin: int = 0     # poin over their limit dropped whole on the retry (never cut)


def _authority(article: dict) -> float:
    return SOURCE_AUTHORITY.get(article["source"].upper(), 0.5)


def pick_articles(articles: Sequence[dict], limit: int = MAX_ARTICLES) -> list:
    """What the model reads: one article per outlet, most authoritative first,
    then the rest by authority, at most `limit`. Stable, so a rerun reads the same."""
    ranked = sorted(articles, key=_authority, reverse=True)
    seen, first, rest = set(), [], []
    for a in ranked:
        (rest if a["source"].upper() in seen else first).append(a)
        seen.add(a["source"].upper())
    return (first + rest)[:limit]


def article_text(article: dict) -> str:
    """What the model reads of one article -- outlet, headline, opening -- and so
    the only text its numbers may come from ("Liputan6" is in it too)."""
    return f"{copy.outlet(article['source'])} — {article['headline']}\n{(article.get('l1_text') or '')[:ARTICLE_CHARS]}"


def source_text(shown: Sequence[dict]) -> str:
    """The number guard's corpus: every shown article's text, without the prompt's own [i] indexes."""
    return "\n\n".join(article_text(a) for a in shown)


def build_prompt(shown: Sequence[dict]) -> str:
    blocks = "\n\n".join(f"[{i}] {article_text(a)}" for i, a in enumerate(shown))
    return PROMPT.format(n=len(shown), articles=blocks)


# ── Checks ──────────────────────────────────────────────────────────────────

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SHORT_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def words(text: str) -> int:
    return len(text.split())


def numbers(text: str) -> List[str]:
    """Every number in `text` as its digits alone: '2.574.000' -> '2574000', '0,46' -> '046'."""
    return [re.sub(r"[.,]", "", m) for m in _NUMBER.findall(text)]


def _date_in(day: int, month: int, source: str) -> bool:
    """True when the source names the date `day/month`: as 4/10, 04/10/2026, or
    '4 Oktober' / '4 Okt'. The prompt asks for 'Minggu (4/10)', which an article
    may have written out. (A 'd/m' copied as it stands, say a score, passes too.)"""
    if re.search(rf"(?<!\d)0?{day}/0?{month}(?!\d)", source):
        return True
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    names = f"(?:{copy.MONTHS[month - 1]}|{copy.MONTHS_SHORT[month - 1]})"
    return bool(re.search(rf"(?<!\d)0?{day}\s+{names}\b", source, re.IGNORECASE))


def unsupported_number(text: str, source: str) -> Optional[str]:
    """The first number in `text` that the source does not contain, or None.
    A short date (4/10) passes when the source names that date in any form."""
    available = set(numbers(source))
    for match in _SHORT_DATE.finditer(text):
        if not _date_in(int(match.group(1)), int(match.group(2)), source):
            return match.group(0)
    rest = _SHORT_DATE.sub(" ", text)
    for raw in _NUMBER.findall(rest):
        if re.sub(r"[.,]", "", raw) not in available:
            return raw
    return None


def _json_object(answer: Optional[str]) -> dict:
    match = re.search(r"\{.*\}", answer or "", re.DOTALL)
    if not match:
        raise Rejected("json", "jawaban bukan JSON")
    try:
        data = json.loads(match.group(0))
    except ValueError:
        raise Rejected("json", "JSON tidak valid")
    if not isinstance(data, dict):
        raise Rejected("json", "JSON harus berupa objek")
    return data


def _text(data: dict, key: str, required: bool = True) -> str:
    value = data.get(key)
    if value is None and not required:
        value = ""          # an optional field left out or null is empty
    if not isinstance(value, str) or (required and not value.strip()):
        raise Rejected("json", f'"{key}" harus teks yang tidak kosong' if required else f'"{key}" harus teks')
    return " ".join(value.split())


def _indexes(data: dict, key: str, n: int) -> List[int]:
    value = data.get(key)
    if value is None and key == "tidak_terkait":
        value = []          # every article was about the event
    if not isinstance(value, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in value):
        raise Rejected("json", f'"{key}" harus daftar nomor artikel')
    if any(not 0 <= i < n for i in value):
        raise Rejected("json", f'"{key}" memuat nomor artikel yang tidak ada (0-{n - 1})')
    if len(set(value)) != len(value):
        raise Rejected("json", f'"{key}" memuat nomor yang sama dua kali')
    return value


def parse(answer: Optional[str], n: int, source: str, drop_long_poin: bool = False) -> StorySummary:
    """The answer as a StorySummary, or Rejected. `n` is the number of articles
    shown, `source` their text (the only place a number may come from).
    `poin`, `mengapa_penting` and `tidak_terkait` may be left out (empty);
    every other field is required.

    drop_long_poin (the retry): a poin over its word limit, or past the second,
    is removed whole instead of refusing the answer -- poin are optional ("Nol poin boleh") and
    nothing is ever cut mid-sentence. The 2026-10-03/04 replays: 133 of 133
    refusals were `length`, nearly all a poin of 21-28 words (EXPERIMENTS.md)."""
    data = _json_object(answer)
    judul, inti, sekilas = _text(data, "judul"), _text(data, "inti"), _text(data, "sekilas")
    mengapa = _text(data, "mengapa_penting", required=False)
    poin = data.get("poin")
    if poin is None:
        poin = []
    if not isinstance(poin, list) or any(not isinstance(p, str) for p in poin):
        raise Rejected("json", '"poin" harus daftar kalimat')
    poin = [" ".join(p.split()) for p in poin if p.strip()]
    kept = [p for p in poin if words(p) <= LIMITS["poin"]][:MAX_POIN] if drop_long_poin else poin
    dropped, poin = len(poin) - len(kept), kept
    terkait, tidak = _indexes(data, "terkait", n), _indexes(data, "tidak_terkait", n)
    if not terkait:
        raise Rejected("json", '"terkait" tidak boleh kosong')
    if set(terkait) & set(tidak) or len(terkait) + len(tidak) != n:
        raise Rejected("json", f"setiap nomor artikel 0-{n - 1} harus muncul tepat sekali di terkait atau "
                               "tidak_terkait")

    # Every broken limit (then every unsupported number) is named at once, so the
    # one retry can repair them all instead of fixing one field and failing on the next.
    problems = [f"poin ada {len(poin)}, maks {MAX_POIN}"] if len(poin) > MAX_POIN else []
    fields = [("judul", judul), ("inti", inti), ("mengapa_penting", mengapa), ("sekilas", sekilas)]
    fields += [(f"poin ke-{k}", p) for k, p in enumerate(poin, 1)]
    for key, value in fields:
        limit = LIMITS[key.split()[0]]
        if words(value) > limit:
            problems.append(f"{key} {words(value)} kata, maks {limit} -- persingkat: \"{value}\"")
    if problems:
        raise Rejected("length", "; ".join(problems))
    for key, value in fields:
        bad = unsupported_number(value, source)
        if bad:
            problems.append(f'angka "{bad}" di {key} tidak ada di artikel')
    if problems:
        raise Rejected("number", "; ".join(problems))
    return StorySummary(judul, inti, poin, mengapa, sekilas, terkait, tidak, dropped)


def summarize_story(summarizer, shown: Sequence[dict], rejections: list) -> Optional[StorySummary]:
    """Ask once, and once more with the reason if the answer is refused. Each
    refusal's reason is appended to `rejections` as it happens (so a failed
    second call still leaves the first counted). None after two refusals.
    The summarizer's own errors (QuotaExhausted, SummarizerError) pass through."""
    source = source_text(shown)
    prompt = build_prompt(shown)
    try:
        return parse(summarizer.summarize(prompt), len(shown), source)
    except Rejected as first:
        rejections.append(first.reason)
        logger.info(f"Summary refused, asking again ({first}) -- {shown[0]['headline'][:80]!r}")
        try:
            return parse(summarizer.summarize(prompt + RETRY.format(detail=first.detail)), len(shown), source,
                         drop_long_poin=True)
        except Rejected as second:
            rejections.append(second.reason)
            logger.info(f"Summary refused again ({second}) -- {shown[0]['headline'][:80]!r}")
            return None
