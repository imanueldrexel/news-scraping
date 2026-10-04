import re
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def preprocess_text(text):
    text = text.strip()
    text = text.replace("\n", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r" {2,}", " ", text)

    return text


def own_paragraph_text(p_tag, separator: str = " ") -> str:
    """SRC-54 (#177): the text of one <p>, without the text of any <p> nested in it.

    A page that leaves <p> unclosed (EMITENNEWS) is parsed by html.parser as a
    chain -- every following <p> becomes a child of the one before. `get_text()`
    of each element then returns that paragraph plus every paragraph after it,
    and a `find_all("p")` loop stores the article body several times over. The
    paragraph's own inline markup (<strong>, <a>, <em>) is kept; only strings
    that sit inside a nested <p> are skipped."""
    parts = []
    for string in p_tag.strings:
        parent = string.parent
        while parent is not None and parent is not p_tag and parent.name != "p":
            parent = parent.parent
        if parent is p_tag:
            parts.append(string)
    return separator.join(s.strip() for s in parts if s.strip())


# A repeated paragraph shorter than this is a legitimate echo ("(*)", a dateline
# on its own line), not a cascade.
CASCADE_MIN_SUFFIX_CHARS = 20


def cascaded_pairs(paragraphs) -> int:
    """SRC-54: how many consecutive paragraph pairs have the second one as a suffix
    of the first -- the signature of nested-<p> extraction. A clean body has 0."""
    paras = [p.strip() for p in (paragraphs or []) if p and p.strip()]
    return sum(
        1 for prev, cur in zip(paras, paras[1:])
        if len(cur) >= CASCADE_MIN_SUFFIX_CHARS and len(cur) < len(prev) and prev.endswith(cur)
    )


def is_cascaded(paragraphs) -> bool:
    """SRC-54: the QA fleet scan's definition -- at least two cascaded pairs."""
    return cascaded_pairs(paragraphs) >= 2


# SYS-63 (#204): lines that belong to the page, not the article. Stored bodies
# carried other stories' headlines ("Baca juga: ..."), ad markers and video
# widgets: 68-100% of the saved articles of 12 sources. The injected headline
# is a different story, so knowledge extraction, the topic probe (body[:500]),
# the L2 chunks and the newsletter's L1 clusters all read it as this article's.
# Every pattern is anchored at the start of a line (prose that merely mentions
# "Google News" survives) and matches what real stored bodies contain.
_BOILERPLATE_LINE = re.compile(
    r"^(?:"
    r"baca\s+(?:juga|selengkapnya)\b.*"                  # KONTAN, ANTARA, MEDIAINDONESIA, BERITASATU ("BACA JUGA")
    r"|lihat\s+juga\b.*"                                  # DETIK, CNN ("Lihat Juga :EDUKASI KEUANGAN ...")
    r"|advertisement"                                     # VIVA, TVONE, LIPUTAN6, MERDEKA
    r"|scroll\s+to\s+continue(?:\s+with\s+content)?"      # DETIK
    r"|gulir\s+untuk\s+lanjut\s+baca"                     # VIVA, TVONE
    r"|berita\s+selengkapnya\b.*"                         # DETIK, CNBC tail
    r"|(?:ikuti|cek|dapatkan|klik|follow|temukan)\b.*\b(?:google\s+news|whatsapp\s+channel|saluran\s+whatsapp)\b.*"
    r")\s*[:|]?\s*$",
    re.IGNORECASE,
)
# Unmistakable widget text, dropped wherever it sits in a line.
_BOILERPLATE_ANYWHERE = re.compile(r"\[gambas:|tautan\s+telah\s+disalin", re.IGNORECASE)
# Editor initials: "(fsd/fsd)" alone on a line, or closing the body. Lowercase
# only, so "(AS/NATO)" and "(yoy/qoq)" mid-sentence are never touched.
_EDITOR_INITIALS = r"\(\s*[a-z]{2,5}\s*/\s*[a-z]{2,5}\s*\)"
_INITIALS_LINE = re.compile(rf"^{_EDITOR_INITIALS}$")
_INITIALS_TAIL = re.compile(rf"\s*{_EDITOR_INITIALS}\s*$")


def is_boilerplate_line(line: str) -> bool:
    line = line.strip()
    return bool(_BOILERPLATE_LINE.match(line) or _BOILERPLATE_ANYWHERE.search(line) or _INITIALS_LINE.match(line))


def clean_body_paragraphs(body):
    """SYS-63: the article body without page chrome and related-headline lines.

    Takes what an extractor returns -- a list of paragraphs, one string, or None --
    and returns the same shape. Works line by line inside each paragraph, because
    trafilatura and several site selectors keep a "Baca Juga: ..." line in the
    middle of a paragraph. A paragraph left empty is dropped; an editor-initials
    tail "(ega/ega)" is cut from the body's last line only."""
    if body is None:
        return None
    paragraphs = [body] if isinstance(body, str) else list(body)
    cleaned = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, str):
            continue
        lines = paragraph.split("\n")
        kept = [line for line in lines if not is_boilerplate_line(line)]
        if len(kept) == len(lines):
            cleaned.append(paragraph)           # nothing to remove: not even whitespace is touched
            continue
        text = "\n".join(kept).strip()
        if text:
            cleaned.append(text)
    if cleaned:
        tail = _INITIALS_TAIL.search(cleaned[-1])
        if tail and cleaned[-1][:tail.start()].strip():
            cleaned[-1] = cleaned[-1][:tail.start()]
    return "\n\n".join(cleaned) if isinstance(body, str) else cleaned
