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
("json"), a field over its word limit ("length" -- never cut mid-sentence), a
number that is not in the `terkait` articles ("number": compared by value, so
"Rp2.574.000" matches "Rp 2.574.000" and "2,574,000", but "Rp1,5" does not match
"Rp15" and "13,3 juta" does not match "13.300.000"; the prompt says to copy
numbers verbatim), or a `terkait` article that does not name the summary's
subject ("subject", SYS-80). A refused answer is asked again once, with the
reason; a second refusal is the caller's fallback (the story's headline list).

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
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
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
ANCHOR_MIN_JUDUL_WORDS = 2     # SYS-80: or a name; see off_subject
REASONS = ("json", "length", "number", "subject")

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
    demoted: int = 0          # terkait articles off the subject moved to tidak_terkait on the retry (SYS-80)


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
    """What the model reads of one article: outlet, headline, opening."""
    return f"{copy.outlet(article['source'])} — {guard_text(article)}"


def guard_text(article: dict) -> str:
    """What the guards read of one article: its headline and opening, as the
    model reads them, without the outlet's name (SYS-87: "Liputan6" is not
    article text, so its 6 is not a number the article states)."""
    return f"{article['headline']}\n{(article.get('l1_text') or '')[:ARTICLE_CHARS]}"


def source_text(articles: Sequence[dict]) -> str:
    """The number guard's corpus over `articles` (the prompt's own [i] indexes and example are not in it)."""
    return "\n\n".join(guard_text(a) for a in articles)


def build_prompt(shown: Sequence[dict]) -> str:
    blocks = "\n\n".join(f"[{i}] {article_text(a)}" for i, a in enumerate(shown))
    return PROMPT.format(n=len(shown), articles=blocks)


# ── Checks ──────────────────────────────────────────────────────────────────

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SHORT_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def words(text: str) -> int:
    return len(text.split())


def _canonical(whole: str, fraction: str = "") -> str:
    whole, fraction = whole.lstrip("0") or "0", fraction.rstrip("0")
    return f"{whole},{fraction}" if fraction else whole


def values(number: str) -> Set[str]:
    """The values a written number can stand for, canonical ('2.574.000' ->
    {'2574000'}, '1,50' -> {'1,5'}), so separators may differ but the decimal
    position may not (SYS-87: 'Rp1,5 triliun' is not 'Rp15 triliun').
    Indonesian notation first ('.' thousands, ',' decimal). The English one is
    read where Indonesian cannot be ('2,574,000', '1.5') and also where both
    can ('1,500': 1,5 or 1500); '1.500' is 1500 only, as Indonesian prose writes it."""
    separators = re.findall(r"[.,]", number)
    if not separators:
        return {_canonical(number)}
    if len(set(separators)) == 2:                       # 2.574,5 / 2,574.5: the last one is the decimal point
        point = max(number.rfind("."), number.rfind(","))
        return {_canonical(re.sub(r"[.,]", "", number[:point]), number[point + 1:])}
    parts = number.split(separators[0])
    if len(parts) > 2:                                  # 2.574.000 / 2,574,000: thousands
        return {_canonical("".join(parts))}
    whole, fraction = parts
    if len(fraction) != 3 or not whole.strip("0"):      # 1,5 / 133,88 / 1.5 / 0,125: a decimal
        return {_canonical(whole, fraction)}
    if separators[0] == ".":
        return {_canonical(whole + fraction)}
    return {_canonical(whole + fraction), _canonical(whole, fraction)}


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
    Numbers are compared by value (`values`). A short date (4/10) passes when
    the source names that date in any form."""
    available = {value for number in _NUMBER.findall(source) for value in values(number)}
    for match in _SHORT_DATE.finditer(text):
        if not _date_in(int(match.group(1)), int(match.group(2)), source):
            return match.group(0)
    rest = _SHORT_DATE.sub(" ", text)
    for number in _NUMBER.findall(rest):
        if not values(number) & available:
            return number
    return None


def off_subject(judul: str, inti: str, related: Dict[int, str]) -> Tuple[List[str], List[int]]:
    """(anchors, strays) for SYS-80 (#236). The anchors are the summary's names
    (`story_words.names` of judul + inti) that a related article mentions. A
    stray is a related article that mentions none of them and fewer than
    ANCHOR_MIN_JUDUL_WORDS of the judul's content words: it is not about the
    story's subject (2026-10-04: "10 Saham Paling Babak Belur, FORU Paling
    Parah" marked `terkait` under "Saham Haji Isam beragam", supplying a FORU
    bullet; it names neither Haji Isam nor PACK, and shares only "saham" with
    the judul). The judul's words let an article that names the subject in
    other words pass ("short selling" without "BEI"; "Perancis" for
    "Prancis"; replay 2026-10-05: names alone flagged ~15 related articles in
    22 refusals). No anchor, no check: a summary without a name an article
    states ("Harga emas naik") cannot be held to one."""
    vocabulary = {i: story_words.vocabulary(text) for i, text in related.items()}
    anchors = sorted(w for w in story_words.names(f"{judul}. {inti}") if any(w in v for v in vocabulary.values()))
    if not anchors:
        return [], []
    judul_words = set(story_words.content_words(judul))
    return anchors, [i for i, v in vocabulary.items()
                     if not v.intersection(anchors) and len(judul_words & v) < ANCHOR_MIN_JUDUL_WORDS]


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


def parse(answer: Optional[str], n: int, sources: Union[str, Sequence[str]],
          drop_long_poin: bool = False, demote_strays: bool = False) -> StorySummary:
    """The answer as a StorySummary, or Rejected. `n` is the number of articles
    shown and `sources` their `guard_text`s, one per article (a string is the
    one article's text). Only the articles marked `terkait` are the summary's
    source: its numbers must be in them, and each of them must name the
    summary's subject (`off_subject`, reason "subject").
    `poin`, `mengapa_penting` and `tidak_terkait` may be left out (empty);
    every other field is required.

    drop_long_poin (the retry): a poin over its word limit, or past the second,
    is removed whole instead of refusing the answer -- poin are optional ("Nol poin boleh") and
    nothing is ever cut mid-sentence. The 2026-10-03/04 replays: 133 of 133
    refusals were `length`, nearly all a poin of 21-28 words (EXPERIMENTS.md).

    demote_strays (the retry): an article still off the subject is moved to
    `tidak_terkait` instead of refusing the answer -- it loses its link and its
    portal, and the number guard then holds the summary to the articles left.
    The model keeps an article it was told about when the article is in fact
    about the story (a spelling the check cannot match), and refusing then
    would lose the whole summary for a portal count (replay 2026-10-05: 13
    stories). A fact it took from a truly unrelated article fails the number
    guard, and the story falls back."""
    texts = [sources] if isinstance(sources, str) else list(sources)
    if len(texts) != n:
        raise ValueError(f"{len(texts)} article texts for {n} articles")
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
    anchors, strays = off_subject(judul, inti, {i: texts[i] for i in terkait})
    demoted = 0
    if strays and demote_strays:
        terkait, tidak, demoted, strays = [i for i in terkait if i not in strays], tidak + strays, len(strays), []
    source = "\n\n".join(texts[i] for i in terkait)
    for key, value in fields:
        bad = unsupported_number(value, source)
        if bad:
            problems.append(f'angka "{bad}" di {key} tidak ada di artikel yang terkait')
    numbers_ok = not problems
    problems += [f'artikel [{i}] tidak menyebut {", ".join(anchors)}: jika membahas peristiwa lain, pindahkan ke '
                 f'"tidak_terkait" dan jangan memakai faktanya' for i in strays]
    if problems:
        raise Rejected("number" if not numbers_ok else "subject", "; ".join(problems))
    return StorySummary(judul, inti, poin, mengapa, sekilas, terkait, tidak, dropped, demoted)


def summarize_story(summarizer, shown: Sequence[dict], rejections: list) -> Optional[StorySummary]:
    """Ask once, and once more with the reason if the answer is refused. Each
    refusal's reason is appended to `rejections` as it happens (so a failed
    second call still leaves the first counted). None after two refusals.
    The summarizer's own errors (QuotaExhausted, SummarizerError) pass through."""
    sources = [guard_text(a) for a in shown]
    prompt = build_prompt(shown)
    try:
        return parse(summarizer.summarize(prompt), len(shown), sources)
    except Rejected as first:
        rejections.append(first.reason)
        logger.info(f"Summary refused, asking again ({first}) -- {shown[0]['headline'][:80]!r}")
        try:
            return parse(summarizer.summarize(prompt + RETRY.format(detail=first.detail)), len(shown), sources,
                         drop_long_poin=True, demote_strays=True)
        except Rejected as second:
            rejections.append(second.reason)
            logger.info(f"Summary refused again ({second}) -- {shown[0]['headline'][:80]!r}")
            return None
