import itertools
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


def unescape_headline(text):
    """SYS-88 (#249): a headline as a reader writes it. Sitemaps hand some titles
    over HTML-escaped ("Jatim &amp; Kalsel", in CDATA the parser does not
    decode), and some twice ("&amp;amp;", DETIK), so unescape until nothing
    changes (bounded: an entity takes at most a few rounds). None stays None."""
    if not text:
        return text
    import html
    for _ in range(5):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text.replace("\xa0", " ")


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
# Every pattern is anchored at the start of a line and matches the SHAPE real
# stored bodies contain, not just a first word (SYS-72 #220: "Lihat juga data BPS
# yang menunjukkan inflasi turun." is a sentence and survives).
#
# A related-link line is the keyword alone, or the keyword, a colon / bar and a
# headline: "Baca juga : <headline>", "Lihat Juga :EDUKASI ... |". The colon or bar
# is what tells them apart: a sentence that merely begins "Baca juga data BPS ..."
# has none. A headline is one short line (some outlets end it with a full stop).
_RELATED_HEADLINE = r"(?:\s*[:|]\s*(?=.{0,250}$).*)?"
# A promo asks the reader to follow the outlet: it starts with an imperative verb
# and names the outlet's own feed or channel ("Ikuti kami di Google News", "Cek
# Berita dan Artikel yang lain di Google News"). "Cek harga emas hari ini di Google
# News" is a sentence about gold prices and survives.
_PROMO_OBJECT = r"(?:berita|artikel|informasi|info|kabar|kami|kita|saluran|channel|update|terbaru|terkini)"
_BOILERPLATE_LINE = re.compile(
    r"^(?:"
    rf"baca\s+juga{_RELATED_HEADLINE}"                    # KONTAN, ANTARA, MEDIAINDONESIA, BERITASATU ("BACA JUGA")
    rf"|lihat\s+juga{_RELATED_HEADLINE}"                  # DETIK, CNN ("Lihat Juga :EDUKASI KEUANGAN ...")
    r"|lihat\s+juga\s+video\b(?=.{0,250}$).*"             # DETIK ("Lihat juga Video: <headline>", colon optional)
    rf"|baca\s+selengkapnya(?:\s+(?:di\s+(?:sini|detik\w+)|melalui\s+tautan\s+ini))?\s*[.>]*{_RELATED_HEADLINE}"   # "Baca selengkapnya di sini ." / ">>>" / ": <headline>"
    r"|advertisement"                                     # VIVA, TVONE, LIPUTAN6, MERDEKA
    r"|scroll\s+to\s+continue(?:\s+with\s+content)?"      # DETIK
    r"|gulir\s+untuk\s+lanjut\s+baca"                     # VIVA, TVONE
    r"|berita\s+selengkapnya(?:\s+(?:baca\s+di\s+sini|tentang\b.{0,80}))?"   # DETIK, CNBC tail, LIPUTAN6
    rf"|(?=.{{0,220}}$)(?:ikuti|cek|dapatkan|klik|follow|temukan)\b(?=.{{0,120}}\b{_PROMO_OBJECT}\b)"
    r".*\b(?:google\s+news|whatsapp\s+channel|saluran\s+whatsapp)\b.*"
    r"|ikuti\s+kumparan\s+di\s+google(?:\s+news)?"         # KUMPARAN (SRC-61), the outlet's name as the object
    r")\s*[:|]?\s*$",
    re.IGNORECASE,
)
# SRC-61 (#280): KUMPARAN's page header, which trafilatura keeps above the body: the headline
# again, the desk ("kumparanNEWS") or the writer's name and title, then a middle dot and
# "waktu baca 2 menit".
# The reading-time line anchors it, within the body's first HEADER_LINES lines; it goes with the
# short lines above it. A line ending in a full stop is prose and stays (SYS-75: never drop prose).
_READING_TIME = re.compile(r"^[\u00b7\u2022]?\s*waktu\s+baca\s+\d+\s+menit$", re.IGNORECASE)
HEADER_LINES = 5
HEADER_LINE_MAX_WORDS = 25
# Unmistakable widget text, removed wherever it sits in a line (SYS-75: the widget,
# not the line -- a paragraph of prose can carry it at its end).
_BOILERPLATE_ANYWHERE = re.compile(r"\[gambas:|tautan\s+telah\s+disalin", re.IGNORECASE)
_WIDGET = re.compile(r"\[gambas:[^\]]*\]", re.IGNORECASE)
# "Tautan telah disalin" is the copy-link toast; the related headlines after it on the
# same line are chrome too, and an unclosed "[Gambas:" runs to the end.
_DANGLING_ELLIPSIS = re.compile(r"\s*\.\.\.\s*$")
_WIDGET_TAIL = re.compile(r"(?:tautan\s+telah\s+disalin|\[gambas:).*$", re.IGNORECASE)
# What must remain of a line once a [Gambas:...] widget is cut for it to be kept as
# prose. A line that was only a widget plus initials or a promo ("(fsd/fsd) Add as a
# preferredsource on Google [Gambas:Video CNBC]") is shorter and is dropped whole, as
# before. After "Tautan telah disalin" no minimum applies: the toast closes a body, so
# what precedes it is the body's last paragraph, however short a quote it is.
MIN_PROSE_AFTER_WIDGET = 120
# Editor initials: "(fsd/fsd)" alone on a line, or closing the body after a
# sentence end. Lowercase only, so "(AS/NATO)" is never touched; and a pair that
# is a finance or English abbreviation ("yoy/qoq", "and/or") is not initials
# whatever it follows (SYS-72).
_EDITOR_INITIALS = r"\(\s*([a-z]{2,5})\s*/\s*([a-z]{2,5})\s*\)"
_NOT_INITIALS = frozenset({"yoy", "qoq", "mom", "mtm", "ytd", "ytm", "and", "or", "dan", "atau", "his", "her", "he", "she"})
_INITIALS_LINE = re.compile(rf"^{_EDITOR_INITIALS}$")
_INITIALS_TAIL = re.compile(rf"(?:(?<=[.!?:\"'\u201d\u2019])|(?<=\n))\s*{_EDITOR_INITIALS}\s*$")


def _is_initials(match) -> bool:
    return bool(match) and not ({match.group(1), match.group(2)} & _NOT_INITIALS)


def clean_line(line: str):
    """SYS-63/SYS-75: the line without page chrome, or None when nothing worth
    keeping is left. A line with nothing to remove comes back unchanged."""
    stripped = line.strip()
    if _BOILERPLATE_LINE.match(stripped) or _is_initials(_INITIALS_LINE.match(stripped)):
        return None
    if not _BOILERPLATE_ANYWHERE.search(stripped):
        return line
    rest = _WIDGET.sub("", stripped)                # a closed widget: cut it, the rest of the line stays
    tail = _WIDGET_TAIL.search(rest)                # the copy-link toast, an unclosed widget: to the end
    if tail:
        rest = rest[:tail.start()]
    rest = _DANGLING_ELLIPSIS.sub("", rest).strip()  # "(anl/ega) ... Tautan telah disalin ..."
    if not rest or _BOILERPLATE_LINE.match(rest) or _is_initials(_INITIALS_LINE.match(rest)):
        return None
    if tail and tail.group(0).lower().startswith("tautan"):
        return rest
    return rest if len(rest) >= MIN_PROSE_AFTER_WIDGET else None


def is_boilerplate_line(line: str) -> bool:
    """True when the whole line is page chrome and is dropped."""
    return clean_line(line) is None


def _reading_time_header(paragraphs) -> set:
    """SRC-61: {(paragraph index, line index)} of a page header that ends in a reading-time line
    among the body's first HEADER_LINES non-empty lines; empty when there is none."""
    lines = ((p_index, l_index, line.strip())
             for p_index, paragraph in enumerate(paragraphs) if isinstance(paragraph, str)
             for l_index, line in enumerate(paragraph.split("\n")) if line.strip())
    first = list(itertools.islice(lines, HEADER_LINES))
    for k, (p_index, l_index, text) in enumerate(first):
        if _READING_TIME.match(text):
            return {(p_index, l_index)} | {
                (p, l) for p, l, above in first[:k]
                if len(above.split()) <= HEADER_LINE_MAX_WORDS and not above.rstrip("\"'\u201d\u2019)").endswith(".")}
    return set()


def clean_body_paragraphs(body):
    """SYS-63: the article body without page chrome and related-headline lines.

    Takes what an extractor returns -- a list of paragraphs, one string, or None --
    and returns the same shape. Works line by line inside each paragraph, because
    trafilatura and several site selectors keep a "Baca Juga: ..." line in the
    middle of a paragraph. A paragraph left empty is dropped; an editor-initials
    tail "(ega/ega)" is cut from the body's last line only; a page header ending in a
    reading-time line is cut from its first lines (SRC-61)."""
    if body is None:
        return None
    paragraphs = [body] if isinstance(body, str) else list(body)
    header = _reading_time_header(paragraphs)
    cleaned = []
    for p_index, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, str):
            continue
        lines = paragraph.split("\n")
        cleaned_lines = [None if (p_index, l_index) in header else clean_line(line)
                         for l_index, line in enumerate(lines)]
        if cleaned_lines == lines:
            cleaned.append(paragraph)           # nothing to remove: not even whitespace is touched
            continue
        kept = [line for line in cleaned_lines if line is not None]
        text = "\n".join(kept).strip()
        if text:
            cleaned.append(text)
    if cleaned:
        tail = _INITIALS_TAIL.search(cleaned[-1])
        if _is_initials(tail) and cleaned[-1][:tail.start()].strip():
            cleaned[-1] = cleaned[-1][:tail.start()]
    return "\n\n".join(cleaned) if isinstance(body, str) else cleaned
