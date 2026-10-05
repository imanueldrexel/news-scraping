"""OPS-40 (#235): render a digest (digests/YYYY-MM-DD.md) as a PDF.

The input is the grammar `NewsletterGenerator` writes, nothing more general:
`# title`, one `> ` line, `---`, `## section`, `### story`, `- ` bullets,
`**Sumber (...)**` / `**Artikel terkait:**` lines whose links are
`[label](url)`, and `*italic*` notes. Every line of the markdown ends up in
the PDF; a line the grammar does not know is printed as a paragraph, never
dropped. Emoji (the section headings carry them) have no glyph in the text
font and are removed.
"""
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus.flowables import KeepTogether

# Dingbats, pictographs, variation selectors and joiners: none has a glyph in the body font.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\uFE00-\uFE0F\u200D]")
_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\*)(.+?)(?<!\*)\*(?![\w*])")

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


def inline(text: str) -> str:
    """Markdown inline (links, bold, italic) -> reportlab paragraph markup, text escaped."""
    out, last = [], 0
    for m in _LINK.finditer(text):
        out.append(_emphasis(text[last:m.start()]))
        out.append('<link href="%s" color="#1a56b0">%s</link>' % (escape(m.group(2), {'"': "&quot;"}),
                                                                 _emphasis(m.group(1))))
        last = m.end()
    out.append(_emphasis(text[last:]))
    return "".join(out)


def _emphasis(text: str) -> str:
    text = escape(_drawable(_EMOJI.sub("", text)))   # not strip_emoji: the spaces around " · " are content
    text = _BOLD.sub(r"<b>\1</b>", text)
    return _ITALIC.sub(r"<i>\1</i>", text)


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
    """The flowables of one digest, in the markdown's order."""
    s = _styles()
    flow, bullets, story_block = [], [], []

    def flush_bullets():
        if bullets:
            story_block.append(ListFlowable([ListItem(Paragraph(inline(b), s["bullet"]), leftIndent=10)
                                             for b in bullets], bulletType="bullet", start="•", leftIndent=10,
                                            bulletFontSize=8))
            bullets.clear()

    def flush_story():
        flush_bullets()
        if story_block:
            flow.append(KeepTogether(story_block[:2]))   # the heading never sits alone at a page foot
            flow.extend(story_block[2:])
            story_block.clear()

    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            flush_story()
            story_block.append(Paragraph(inline(line[4:]), s["story"]))
        elif line.startswith("## "):
            flush_story()
            flow.append(Paragraph(inline(line[3:]), s["section"]))
        elif line.startswith("# "):
            flush_story()
            flow.append(Paragraph(inline(line[2:]), s["title"]))
        elif line.startswith("> "):
            flow.append(Paragraph(inline(line[2:]), s["quote"]))
        elif line.strip() == "---":
            flush_story()
            flow.append(Spacer(1, 3))
            flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#bbbbbb")))
        elif line.startswith("- "):
            bullets.append(line[2:])
        elif line.startswith("**"):
            flush_bullets()
            story_block.append(Paragraph(inline(line), s["meta"]))
        else:
            flush_story()
            flow.append(Paragraph(inline(line), s["para"]))
    flush_story()
    return flow


def _footer(canvas, doc):
    regular = _register_fonts()[0]
    canvas.saveState()
    canvas.setFont(regular, 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, "%s  ·  %d" % (doc.title, doc.page))
    canvas.restoreState()


def render_digest_pdf(markdown_path: str, pdf_path: str = None) -> str:
    """Write the PDF next to the markdown (or at `pdf_path`) and return its path.
    Written to a temporary name and renamed, so a failed render leaves no partial file."""
    with open(markdown_path, encoding="utf-8") as f:
        markdown = f.read()
    pdf_path = pdf_path or os.path.splitext(markdown_path)[0] + ".pdf"
    title = os.path.splitext(os.path.basename(markdown_path))[0]
    tmp = pdf_path + ".tmp"
    try:
        doc = SimpleDocTemplate(tmp, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm,
                                bottomMargin=16 * mm, title="Rangkuman Berita %s" % title, author="NewsAggregator")
        doc.build(build_story(markdown), onFirstPage=_footer, onLaterPages=_footer)
        os.replace(tmp, pdf_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return pdf_path
