"""OPS-40 (#235): render a digest (digests/YYYY-MM-DD.md) as a PDF; OPS-42 (#242):
render the 5-minute edition (digests/YYYY-MM-DD-ringkas.md) as a phone-sized PDF.

The input is the grammar the newsletter writes, nothing more general: `# title`,
`> ` lines, `---`, `## section`, `### story`, `- ` bullets, `**label:** ...`
lines, plain paragraphs, links `[label](url)` and `*italic*` notes. `parse`
turns it into blocks; `build_story` (A4 archive) and `build_edition_story`
(phone) lay the blocks out. Every line of the markdown ends up in the PDF; a
line the grammar does not know is printed as a paragraph, never dropped. Emoji
(the section headings carry them) have no glyph in the text font and are removed.

Page breaks (OPS-41 #238): a whole story -- heading, summary, bullets, source and
link lines -- is one KeepTogether, so it moves to the next page whole (only a
story longer than a page is split), and a section heading shares a KeepTogether
with whatever follows it, so it never sits alone at a page foot.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table
from reportlab.platypus.flowables import KeepTogether

from newscrawler.core import newsletter_copy as copy

# Dingbats, pictographs, variation selectors and joiners: none has a glyph in the body font.
# U+2192 (the "Baca di ... →" arrow) is kept: Arial and DejaVu both draw it.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2190-\u2191\u2193-\u21FF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF"
                    "\uFE00-\uFE0F\u200D]")
_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\*)(.+?)(?<!\*)\*(?![\w*])")
_DATE_IN_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_REPORTED = re.compile(r"^\*\*" + re.escape(copy.REPORTED_BY).replace(r"\{n\}", r"(\d[\d.]*)") + r"\*\*\s*(?:·\s*)?")

LINK_COLOR = "#1a56b0"     # 7.0:1 on white
FOOTER_COLOR = "#666666"   # 5.7:1 on white (OPS-42: #777777 was 4.48:1, under WCAG AA)

# Fonts with the full Latin range, first found wins; reportlab's built-in Helvetica is the floor.
_FONT_CANDIDATES = (
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
)
_BODY_FONT = None


def _register_fonts():
    """(regular, bold, italic) font names; registered once."""
    global _BODY_FONT
    if _BODY_FONT:
        return _BODY_FONT
    for regular, bold, italic in _FONT_CANDIDATES:
        if all(os.path.exists(p) for p in (regular, bold, italic)):
            pdfmetrics.registerFont(TTFont("NewsBody", regular))
            pdfmetrics.registerFont(TTFont("NewsBody-Bold", bold))
            pdfmetrics.registerFont(TTFont("NewsBody-Italic", italic))
            pdfmetrics.registerFontFamily("NewsBody", normal="NewsBody", bold="NewsBody-Bold",
                                          italic="NewsBody-Italic", boldItalic="NewsBody-Bold")
            _BODY_FONT = ("NewsBody", "NewsBody-Bold", "NewsBody-Italic")
            return _BODY_FONT
    _BODY_FONT = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique")
    return _BODY_FONT


def _drawable(text: str) -> str:
    """`text` with every character the body font has no glyph for (CJK, say) replaced by "?": a blank
    box on the page, in text a reader cannot search, would hide that something was there."""
    glyphs = getattr(getattr(pdfmetrics.getFont(_register_fonts()[0]), "face", None), "charToGlyph", None)
    if glyphs is None:   # built-in Helvetica: reportlab substitutes what it cannot encode
        return text
    return "".join(c if ord(c) in glyphs or c in "\t\n" else "?" for c in text)


def strip_emoji(text: str) -> str:
    return _EMOJI.sub("", text).strip()


def inline(text: str, link_color: str = LINK_COLOR) -> str:
    """Markdown inline (links, bold, italic) -> reportlab paragraph markup, text escaped."""
    out, last = [], 0
    for m in _LINK.finditer(text):
        out.append(_emphasis(text[last:m.start()]))
        out.append('<link href="%s" color="%s">%s</link>' % (escape(m.group(2), {'"': "&quot;"}), link_color,
                                                             _emphasis(m.group(1))))
        last = m.end()
    out.append(_emphasis(text[last:]))
    return "".join(out)


def _emphasis(text: str) -> str:
    text = escape(_drawable(_EMOJI.sub("", text)))   # not strip_emoji: the spaces around " · " are content
    text = _BOLD.sub(r"<b>\1</b>", text)
    return _ITALIC.sub(r"<i>\1</i>", text)


# ── Parsing ──────────────────────────────────────────────────────────────────

@dataclass
class Block:
    """One unit of the newsletter grammar. `kind` is title, quote, rule, section,
    story, bullets or para. A story's `items` are ("para", text), ("bullets",
    [text, ...]) and ("meta", text) in order; a top-level bullets block's
    `items` are its texts."""
    kind: str
    text: str = ""
    items: list = field(default_factory=list)


def parse(markdown: str) -> List[Block]:
    """The blocks of a newsletter, in the markdown's order. A `### ` heading
    opens a story that holds every following line up to the next heading,
    quote or `---`; outside a story, consecutive `- ` lines form one bullets
    block and anything else is a paragraph."""
    blocks: List[Block] = []
    story: Optional[Block] = None

    def close_story():
        nonlocal story
        if story is not None:
            blocks.append(story)
            story = None

    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            close_story()
            story = Block("story", line[4:])
        elif line.startswith("## "):
            close_story()
            blocks.append(Block("section", line[3:]))
        elif line.startswith("# "):
            close_story()
            blocks.append(Block("title", line[2:]))
        elif line.startswith("> "):
            close_story()
            blocks.append(Block("quote", line[2:]))
        elif line.strip() == "---":
            close_story()
            blocks.append(Block("rule"))
        elif line.startswith("- "):
            target = story.items if story is not None else None
            if target is not None:
                if target and target[-1][0] == "bullets":
                    target[-1][1].append(line[2:])
                else:
                    target.append(("bullets", [line[2:]]))
            elif blocks and blocks[-1].kind == "bullets":
                blocks[-1].items.append(line[2:])
            else:
                blocks.append(Block("bullets", items=[line[2:]]))
        elif story is not None:
            story.items.append(("meta" if line.startswith("**") else "para", line))
        else:
            blocks.append(Block("para", line))
    close_story()
    return blocks


class _Flow:
    """The flowable list, holding a section heading back until the block after
    it arrives so the two share one KeepTogether (OPS-41)."""

    def __init__(self):
        self.flow, self.pending = [], []

    def hold(self, flowables):
        self.pending.extend(flowables)

    def keep(self, flowables):
        """One block that must not be split from its heading (if any)."""
        self.flow.append(KeepTogether(self.pending + list(flowables)))
        self.pending = []

    def free(self, flowables):
        """A block nothing needs to stay with; a held heading is released as is."""
        self.flow.extend(self.pending)
        self.pending = []
        self.flow.extend(flowables)

    def done(self):
        self.free([])
        return self.flow


def _bullet_list(texts, style, bullet_size=8):
    return ListFlowable([ListItem(Paragraph(inline(t), style), leftIndent=10) for t in texts],
                        bulletType="bullet", start="•", leftIndent=10, bulletFontSize=bullet_size)


# ── A4 archive (the full digest) ─────────────────────────────────────────────

def _styles():
    regular, bold, italic = _register_fonts()
    base = ParagraphStyle("base", fontName=regular, fontSize=9.5, leading=13, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", parent=base, fontName=bold, fontSize=20, leading=24, spaceAfter=4),
        "quote": ParagraphStyle("quote", parent=base, textColor=colors.HexColor("#555555"), spaceAfter=8),
        "section": ParagraphStyle("section", parent=base, fontName=bold, fontSize=14, leading=18, spaceBefore=10,
                                  spaceAfter=6, textColor=colors.HexColor("#0b3d7a")),
        "story": ParagraphStyle("story", parent=base, fontName=bold, fontSize=11, leading=14, spaceBefore=8,
                                spaceAfter=3),
        "bullet": ParagraphStyle("bullet", parent=base, spaceAfter=2),
        "meta": ParagraphStyle("meta", parent=base, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#333333"),
                               spaceAfter=2),
        "para": base,
    }


def build_story(markdown: str):
    """The A4 flowables of one digest, in the markdown's order."""
    s = _styles()
    out = _Flow()
    for block in parse(markdown):
        if block.kind == "story":
            flowables = [Paragraph(inline(block.text), s["story"])]
            for kind, value in block.items:
                if kind == "bullets":
                    flowables.append(_bullet_list(value, s["bullet"]))
                else:   # source and link lines are small print; "Mengapa penting" is part of the summary
                    small = kind == "meta" and not value.startswith("**" + copy.WHY_IT_MATTERS)
                    flowables.append(Paragraph(inline(value), s["meta" if small else "para"]))
            out.keep(flowables)
        elif block.kind == "section":
            out.hold([Paragraph(inline(block.text), s["section"])])
        elif block.kind == "title":
            out.free([Paragraph(inline(block.text), s["title"])])
        elif block.kind == "quote":
            out.keep([Paragraph(inline(block.text), s["quote"])])
        elif block.kind == "rule":
            out.free([Spacer(1, 3), HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#bbbbbb"))])
        elif block.kind == "bullets":
            out.keep([_bullet_list(block.items, s["bullet"])])
        else:
            out.keep([Paragraph(inline(block.text), s["para"])])
    return out.done()


# ── Phone edition (OPS-42) ───────────────────────────────────────────────────

PHONE_PAGE = (105 * mm, 190 * mm)
PHONE_MARGIN = 10 * mm
PHONE_BODY_SIZE = 11.5
BAND_BG = "#e6eef8"
BOX_BG = "#f2f5f9"
ACCENT = "#0b3d7a"
TEXT_COLOR = "#1a1a1a"


def _phone_styles():
    regular, bold, italic = _register_fonts()
    body = ParagraphStyle("p_body", fontName=regular, fontSize=PHONE_BODY_SIZE, leading=16, alignment=TA_LEFT,
                          textColor=colors.HexColor(TEXT_COLOR), spaceAfter=4)
    return {
        "title": ParagraphStyle("p_title", parent=body, fontName=bold, fontSize=20, leading=24, spaceAfter=2),
        "quote": ParagraphStyle("p_quote", parent=body, fontSize=10.5, leading=14, spaceAfter=6,
                                textColor=colors.HexColor("#555555")),
        "band": ParagraphStyle("p_band", parent=body, fontName=bold, fontSize=10, leading=13, spaceBefore=10,
                               spaceAfter=8, textColor=colors.HexColor(ACCENT), backColor=colors.HexColor(BAND_BG),
                               borderPadding=(4, 4, 4, 4)),
        "box_head": ParagraphStyle("p_box_head", parent=body, fontName=bold, fontSize=12, leading=16, spaceAfter=4,
                                   textColor=colors.HexColor(ACCENT)),
        "story": ParagraphStyle("p_story", parent=body, fontName=bold, fontSize=14, leading=18, spaceBefore=8,
                                spaceAfter=4),
        "lead": ParagraphStyle("p_lead", parent=body, fontName=bold, fontSize=16, leading=20, spaceBefore=4,
                               spaceAfter=4),
        "body": body,
        "bullet": ParagraphStyle("p_bullet", parent=body, spaceAfter=3),
        "read": ParagraphStyle("p_read", parent=body, fontSize=10.5, leading=16, spaceBefore=2, spaceAfter=6),
        "glance": ParagraphStyle("p_glance", parent=body, fontSize=10.5, leading=14.5, spaceAfter=3),
        "small": ParagraphStyle("p_small", parent=body, fontSize=9, leading=12.5, textColor=colors.HexColor("#444444")),
    }


def _badge(n: str) -> str:
    """'Diberitakan N portal' as a tinted label after the title; its spaces do not
    break, so it moves to the next line whole instead of splitting."""
    label = escape(copy.REPORTED_BY.format(n=n)).replace(" ", "&nbsp;")
    return ' <font size="9" color="%s" backColor="%s">&nbsp;%s&nbsp;</font>' % (ACCENT, BAND_BG, label)


def _edition_story(block: Block, s: dict, lead: bool) -> list:
    """Title (linked) with the portal badge beside it, the summary, the bullets,
    'Mengapa penting', and one 'Baca di' link on a line of its own (a tap target)."""
    badge, rest = "", []
    for kind, value in block.items:
        reported = _REPORTED.match(value) if kind == "meta" else None
        if reported:
            badge = _badge(reported.group(1))
            tail = value[reported.end():].strip()
            if tail:
                rest.append(("read", tail))
        else:
            rest.append((kind, value))
    # The title links to the lead article in the text colour: the visible link is the
    # "Baca di ... →" line, marked by colour and the arrow, never colour alone (OPS-42).
    flowables = [Paragraph(inline(block.text, link_color=TEXT_COLOR) + badge, s["lead" if lead else "story"])]
    for kind, value in rest:
        if kind == "bullets":
            flowables.append(_bullet_list(value, s["bullet"], bullet_size=9))
        elif kind == "read":
            flowables.append(Paragraph(inline(value), s["read"]))
        else:   # the summary sentence and "Mengapa penting" are body text, not small print
            flowables.append(Paragraph(inline(value), s["body"]))
    return flowables


def build_edition_story(markdown: str):
    """The phone flowables of one 5-minute edition."""
    s = _phone_styles()
    out = _Flow()
    blocks = parse(markdown)
    section, first_in_section = "", False
    for i, block in enumerate(blocks):
        if block.kind == "section":
            section, first_in_section = strip_emoji(block.text), True
            boxed = section == copy.SIXTY_SECONDS and i + 1 < len(blocks) and blocks[i + 1].kind == "bullets"
            if not boxed:   # (a 60-second heading with no bullets is an ordinary band: never lost)
                out.hold([Paragraph(escape(_drawable(section.upper())), s["band"])])
        elif block.kind == "bullets" and section == copy.SIXTY_SECONDS and blocks[i - 1].kind == "section":
            # the heading and its sentences, drawn together as one tinted box
            box = Table([[[Paragraph(escape(_drawable(section)), s["box_head"]),
                           _bullet_list(block.items, s["body"], bullet_size=9)]]],
                        colWidths=[PHONE_PAGE[0] - 2 * PHONE_MARGIN])
            box.setStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BOX_BG)),
                          ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                          ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])
            out.keep([Spacer(1, 4), box, Spacer(1, 4)])
            section = ""
        elif block.kind == "story":
            out.keep(_edition_story(block, s, lead=first_in_section and section == copy.TOP_STORIES))
            first_in_section = False
        elif block.kind == "bullets":
            out.keep([_bullet_list(block.items, s["glance"], bullet_size=8)])
        elif block.kind == "title":
            out.free([Paragraph(inline(block.text), s["title"])])
        elif block.kind == "quote":
            out.keep([Paragraph(inline(block.text), s["quote"])])
        elif block.kind == "rule":
            out.free([Spacer(1, 4), HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#bbbbbb")),
                      Spacer(1, 2)])
        else:
            out.keep([Paragraph(inline(block.text), s["small"])])
    return out.done()


# ── Rendering ────────────────────────────────────────────────────────────────

def date_of(markdown_path: str) -> Optional[date]:
    """The digest's date from its file name (YYYY-MM-DD.md, YYYY-MM-DD-ringkas.md), or None."""
    match = _DATE_IN_NAME.match(os.path.basename(markdown_path))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def footer_label(markdown_path: str) -> str:
    """'Rangkuman Berita · Minggu, 4 Okt 2026' (SYS-81: never the ISO date)."""
    d = date_of(markdown_path)
    return copy.caption(d) if d else copy.TITLE


def _numbered_canvas(label: str, page_width: float, right_margin: float):
    """A canvas that writes '<label> · page/total' at the foot of every page;
    the total is known only once every page is laid out, so pages are kept
    until save()."""
    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFont(_register_fonts()[0], 8)
                self.setFillColor(colors.HexColor(FOOTER_COLOR))
                self.drawRightString(page_width - right_margin, 6 * mm,
                                     _drawable("%s · %d/%d" % (label, self._pageNumber, total)))
                self.restoreState()
                super().showPage()
            super().save()
    return NumberedCanvas


def _render(markdown_path: str, pdf_path: Optional[str], builder, pagesize, margins) -> str:
    """Write the PDF next to the markdown (or at `pdf_path`) and return its path.
    Written to a temporary name and renamed, so a failed render leaves no partial file."""
    with open(markdown_path, encoding="utf-8") as f:
        markdown = f.read()
    pdf_path = pdf_path or os.path.splitext(markdown_path)[0] + ".pdf"
    label = footer_label(markdown_path)
    left, right, top, bottom = margins
    tmp = pdf_path + ".tmp"
    try:
        doc = SimpleDocTemplate(tmp, pagesize=pagesize, leftMargin=left, rightMargin=right, topMargin=top,
                                bottomMargin=bottom, title=label, author="NewsAggregator")
        doc.build(builder(markdown), canvasmaker=_numbered_canvas(label, pagesize[0], right))
        os.replace(tmp, pdf_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return pdf_path


def render_digest_pdf(markdown_path: str, pdf_path: str = None) -> str:
    """The full digest as an A4 PDF (the archive)."""
    return _render(markdown_path, pdf_path, build_story, A4, (16 * mm, 16 * mm, 15 * mm, 16 * mm))


def render_edition_pdf(markdown_path: str, pdf_path: str = None) -> str:
    """The 5-minute edition as a narrow phone PDF (OPS-42)."""
    return _render(markdown_path, pdf_path, build_edition_story, PHONE_PAGE,
                   (PHONE_MARGIN, PHONE_MARGIN, PHONE_MARGIN, PHONE_MARGIN + 3 * mm))
