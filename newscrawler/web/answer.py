"""The search answer as data (SYS-99 #268, SYS-93 #262).

The model's text is untrusted: it is built from scraped pages. It is never
rendered as markup. It is cleaned of Markdown, then parsed into blocks
(paragraphs and bullet lists) of segments, each either text or a citation
number. A citation becomes a link only when it names a source card that exists,
and the link's target is built from the card's index, never from the text.

`unverified_number` holds the answer's numbers to the articles it cites, with
the newsletter's value comparison (`story_summary.unsupported_number`, SYS-87).
"""
import re
from datetime import date
from typing import Iterable, List, NamedTuple, Optional, Sequence

from newscrawler.core import web_copy as copy
from newscrawler.core.newsletter_copy import outlet, tanggal
from newscrawler.core.source_check import unsupported_number

LEAD_CHARS = 400        # the article's opening (L1 chunk): who, what, when
MATCH_CHARS = 700       # the paragraph that matched the question (L2 chunk)
HISTORY_TURNS = 3
MAX_RANGE = 5           # [1-3] expands; [1-40] is not a citation

PROMPT = (
    "Kamu redaktur yang menjawab pertanyaan pembaca hanya dari artikel bernomor di bawah.\n"
    "Hari ini {hari_ini}.\n\n"
    "Aturan:\n"
    "- Kalimat pertama langsung menjawab. Lalu paling banyak 3 poin pendukung. Total maks. 120 kata.\n"
    "- Setiap fakta diberi nomor artikelnya, mis. [2] atau [1][3]. Jangan tulis nama portal atau tanggal "
    "sebagai kutipan.\n"
    "- Salin angka persis seperti di artikel. Sebut tanggal kejadian (mis. \"Senin, 5 Oktober\"), bukan "
    "\"kemarin\".\n"
    "- Teks biasa: tanpa Markdown, tanpa tebal, poin diawali \"- \".\n"
    "- Jangan sebut \"konteks\", \"artikel yang diberikan\", atau \"sebagai AI\".\n"
    "- Jika artikel tidak cukup, tulis persis: \"{tidak_cukup}\" lalu sebut apa yang memang dikatakan artikel.\n"
    "- Riwayat percakapan hanya untuk memahami rujukan (\"itu\", \"perusahaan tadi\"), bukan sumber fakta.\n\n"
    "Artikel:\n{artikel}\n\n"
    "Riwayat:\n{riwayat}\n\n"
    "Pertanyaan: {pertanyaan}"
)
NO_HISTORY = "Tidak ada."


class Segment(NamedTuple):
    kind: str               # "text" | "cite"
    text: str = ""
    n: int = 0              # the source card's number for a "cite"


class Block(NamedTuple):
    kind: str               # "p" | "ul"
    items: List[List[Segment]]  # one segment list for a paragraph, one per bullet for a list


# ── Prompt ──────────────────────────────────────────────────────────────────

def header(hit: dict) -> str:
    """'Kontan · Senin, 5 Okt 2026 · Judul' -- what the model and the number check read."""
    parts = [outlet(hit.get("source", "")), copy.tanggal_kartu(hit.get("posted_date")), hit.get("title", "")]
    return " · ".join(p for p in parts if p)


def excerpt(hit: dict) -> str:
    """The article's lead, then the paragraph that matched, without repeating the lead."""
    match = (hit.get("text_content") or "").strip()[:MATCH_CHARS]
    lead = (hit.get("l1_text") or "").strip()[:LEAD_CHARS]
    if not lead or lead[:120] in match or match[:120] in lead:
        return match or lead
    return f"{lead} … {match}"


def article_block(n: int, hit: dict) -> str:
    return f"[{n}] {header(hit)}\n{excerpt(hit)}"


def strip_citations(text: str) -> str:
    return re.sub(r"\s*" + _CITE.pattern, "", text).strip()


def history_text(history: Sequence[dict]) -> str:
    """The last turns, citations removed: the old [n] point at another article list."""
    turns = [t for t in history if t.get("answer")][-HISTORY_TURNS:]
    if not turns:
        return NO_HISTORY
    return "\n".join(f"T: {t['question']}\nJ: {strip_citations(t['answer'])}" for t in turns)


def build_prompt(question: str, hits: Sequence[dict], history: Sequence[dict], today: date) -> str:
    return PROMPT.format(hari_ini=tanggal(today), tidak_cukup=copy.NOT_ENOUGH,
                         artikel="\n\n".join(article_block(i, h) for i, h in enumerate(hits, 1)),
                         riwayat=history_text(history), pertanyaan=question.strip())


# ── Cleanup and parsing ─────────────────────────────────────────────────────

_CITE = re.compile(r"\[(\s*\d+\s*(?:[,;–—-]\s*\d+\s*)*)\]")
_BULLET = re.compile(r"^\s*(?:[-*•·+]|\d{1,2}[.)])\s+")


def clean(text: str) -> str:
    """Plain text from what the model wrote: no Markdown emphasis, headings or code marks;
    every bullet starts with '- '. Citations are left alone."""
    text = (text or "").replace("\r\n", "\n").replace("`", "")
    text = re.sub(r"\*\*|__", "", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*#{1,6}\s+", "", line)
        if _BULLET.match(line):
            line = "- " + _BULLET.sub("", line, count=1)
        line = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", line)  # *emphasis*
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _numbers(inner: str) -> Optional[List[int]]:
    out: List[int] = []
    for part in re.split(r"[,;]", inner):
        bounds = [int(b) for b in re.split(r"[–—-]", part) if b.strip()]
        if len(bounds) == 1:
            out.append(bounds[0])
        elif len(bounds) == 2 and 0 < bounds[1] - bounds[0] < MAX_RANGE:
            out.extend(range(bounds[0], bounds[1] + 1))
        else:
            return None
    return out


def segments(text: str, n_sources: int) -> List[Segment]:
    """Text and citation segments. A bracket naming any number outside 1..n_sources stays text whole."""
    out: List[Segment] = []
    pos = 0
    for m in _CITE.finditer(text):
        numbers = _numbers(m.group(1))
        if not numbers or not all(1 <= n <= n_sources for n in numbers):
            continue
        if m.start() > pos:
            out.append(Segment("text", text[pos:m.start()]))
        out.extend(Segment("cite", f"[{n}]", n) for n in numbers)
        pos = m.end()
    if pos < len(text):
        out.append(Segment("text", text[pos:]))
    return out


def parse(text: str, n_sources: int) -> List[Block]:
    """Paragraphs and bullet lists of segments, from cleaned text."""
    blocks: List[Block] = []
    paragraph: List[str] = []

    def flush():
        if paragraph:
            blocks.append(Block("p", [segments(" ".join(paragraph), n_sources)]))
            paragraph.clear()

    for line in text.split("\n"):
        if not line.strip():
            flush()
        elif line.startswith("- "):
            flush()
            item = segments(line[2:].strip(), n_sources)
            if blocks and blocks[-1].kind == "ul":
                blocks[-1].items.append(item)
            else:
                blocks.append(Block("ul", [item]))
        else:
            paragraph.append(line.strip())
    flush()
    return blocks


def cited(blocks: Iterable[Block]) -> List[int]:
    """The card numbers the answer cites, in order of first use."""
    seen: List[int] = []
    for block in blocks:
        for item in block.items:
            for seg in item:
                if seg.kind == "cite" and seg.n not in seen:
                    seen.append(seg.n)
    return seen


def unverified_number(text: str, hits: Sequence[dict], cited_numbers: Sequence[int], today: date) -> Optional[str]:
    """The first number in the answer that the cited articles (all of them when none is
    cited) do not contain, or None. Today's date is in the prompt, so it counts as a source."""
    chosen = [hits[n - 1] for n in cited_numbers if 1 <= n <= len(hits)] or list(hits)
    corpus = "\n".join([tanggal(today)] + [f"{header(h)}\n{excerpt(h)}" for h in chosen])
    return unsupported_number(strip_citations(text), corpus)
