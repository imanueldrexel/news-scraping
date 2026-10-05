"""OPS-40 (#235): a digest becomes a PDF that holds what the markdown holds.

The tests read the PDF back (text and link annotations) and compare it with the
markdown, so a renderer that drops a story, a link or the spaces between links
fails here -- not only one that crashes.
"""
import os
import re

import pytest
from pypdf import PdfReader

from newscrawler.core.newsletter_pdf import inline, render_digest_pdf, render_edition_pdf, strip_emoji

DIGEST = """# Rangkuman Berita — 4 October 2026

> Dibuat otomatis dari portal berita Indonesia | 12:05 WIB

---

## 📈 Pasar

### Harga Emas Antam Stagnan pada Minggu (4/10), Rp 2.574.000 per Gram

- Harga emas batangan Antam stagnan di level Rp 2.574.000 per gram.
- Laba PT A & B naik <10% dibanding tahun lalu, kata *analis*.

**Sumber (2 portal):** KONTAN · CNBC
**Artikel terkait:** [KONTAN: Harga Emas Antam](https://investasi.kontan.co.id/news/emas?page=all) · [CNBC: Emas Ambruk](https://www.cnbcindonesia.com/research/emas?page=all)

*…dan 16 berita lainnya di bagian ini.*

---

## 🏛️ Politik

### Komisi VIII DPR dan Kemenag Dorong Pendidikan Inklusif

- Wakil Ketua Komisi VIII DPR menyatakan madrasah menghadapi tantangan.

**Sumber (1 portal):** TRIBUN
**Artikel terkait:** [TRIBUN: Madrasah Hadapi Tantangan](https://www.tribunnews.com/nasional/1?page=all)

---

*Total artikel hari ini: 1798 | Cluster teridentifikasi: 268 | Ringkasan AI: 90/90 (deepseek-v4-flash)*
"""


def _read(pdf):
    reader = PdfReader(pdf)
    text = "\n".join(page.extract_text() for page in reader.pages)
    uris = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            action = annot.get_object().get("/A") or {}
            if action.get("/URI"):
                uris.append(str(action["/URI"]))
    return text, uris


def _squash(text):
    return re.sub(r"\s+", " ", text)


@pytest.fixture
def pdf(tmp_path):
    md = tmp_path / "2026-10-04.md"
    md.write_text(DIGEST, encoding="utf-8")
    return render_digest_pdf(str(md))


class TestContent:
    def test_the_pdf_is_written_next_to_the_markdown(self, pdf, tmp_path):
        assert pdf == str(tmp_path / "2026-10-04.pdf") and os.path.getsize(pdf) > 1000
        assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]

    def test_every_heading_of_the_markdown_is_in_the_pdf(self, pdf):
        text = _squash(_read(pdf)[0])
        headings = [strip_emoji(l.lstrip("# ")) for l in DIGEST.splitlines() if l.startswith("#")]
        assert len(headings) == 5
        for heading in headings:
            assert heading in text, heading

    def test_every_bullet_and_the_footer_are_in_the_pdf(self, pdf):
        text = _squash(_read(pdf)[0])
        for line in DIGEST.splitlines():
            if line.startswith("- "):
                plain = line[2:].replace("*", "")
                assert plain in text, plain
        assert "Total artikel hari ini: 1798" in text and "dan 16 berita lainnya di bagian ini." in text

    def test_every_link_is_a_working_link_annotation(self, pdf):
        uris = set(_read(pdf)[1])
        expected = set(re.findall(r"\]\((https?://[^)]+)\)", DIGEST))
        assert len(expected) == 3 and expected <= uris

    def test_link_labels_keep_their_separator_and_the_source_line(self, pdf):
        text = _squash(_read(pdf)[0])
        assert "KONTAN: Harga Emas Antam · CNBC: Emas Ambruk" in text
        assert "Sumber (2 portal): KONTAN · CNBC" in text
        assert "Artikel terkait: KONTAN" in text

    def test_emoji_are_dropped_and_leave_no_box_or_marker(self, pdf):
        text = _read(pdf)[0]
        assert not re.search("[\U0001F000-\U0001FAFF☀-➿️]", text)
        assert "Pasar" in text and "Politik" in text

    def test_markup_characters_in_a_story_are_text_not_markup(self, pdf):
        text = _squash(_read(pdf)[0])
        assert "Laba PT A & B naik <10% dibanding tahun lalu, kata analis." in text

    @pytest.mark.parametrize("edition", [True, False], ids=["edition", "digest"])
    def test_text_that_reads_as_markup_is_printed_verbatim(self, tmp_path, edition):
        """DBT-58 (#253): "<" before a letter, or a tag, in a story's text is not reportlab markup. Unescaped,
        "harga <Rp1.000" raises "parse ended with 1 unclosed tags" and the reader gets no PDF. ("<10%" and
        "A & B" above are tolerated by the parser, so they did not show it.)"""
        md = ("# Rangkuman Berita\n\n## Berita Utama\n\n"
              "### [Saham S&P <b>naik harga <Rp1.000](https://x.example/a?b=1&c=2)\n\n"
              "Tarif PPN 12% <b>naik untuk barang <Rp1.000 & jasa.\n\n"
              "- Poin dengan <i>miring dan <Rp500.\n\n"
              "**Diberitakan 3 portal** · [Baca di S&P <Global> →](https://x.example/a?b=1&c=2)\n")
        path = tmp_path / ("2026-10-04-ringkas.md" if edition else "2026-10-04.md")
        path.write_text(md, encoding="utf-8")
        render = render_edition_pdf if edition else render_digest_pdf
        text, uris = _read(render(str(path)))
        text = _squash(text)
        for line in ("Saham S&P <b>naik harga <Rp1.000", "Tarif PPN 12% <b>naik untuk barang <Rp1.000 & jasa.",
                     "Poin dengan <i>miring dan <Rp500.", "Baca di S&P <Global>"):
            assert line in text, line
        assert "https://x.example/a?b=1&c=2" in uris

    def test_a_line_the_grammar_does_not_know_is_printed_not_dropped(self, tmp_path):
        md = tmp_path / "d.md"
        md.write_text("# t\n\nA line nobody planned for.\n\n1. numbered\n", encoding="utf-8")
        text = _squash(_read(render_digest_pdf(str(md)))[0])
        assert "A line nobody planned for." in text and "1. numbered" in text

    def test_a_long_digest_flows_over_pages_without_losing_stories(self, tmp_path):
        stories = "".join("### Story number %d\n\n- bullet of %d\n\n**Sumber (1 portal):** X\n\n" % (i, i)
                          for i in range(300))
        md = tmp_path / "d.md"
        md.write_text("# t\n\n## S\n\n" + stories, encoding="utf-8")
        pdf = render_digest_pdf(str(md))
        assert len(PdfReader(pdf).pages) > 5
        text = _squash(_read(pdf)[0])
        assert all(("Story number %d" % i) in text for i in range(300))


class TestRobustness:
    def test_characters_outside_the_font_do_not_crash(self, tmp_path):
        md = tmp_path / "d.md"
        md.write_text("# t\n\n### Judul 中文 ok\n\n- 😀 isi\n", encoding="utf-8")
        text = _squash(_read(render_digest_pdf(str(md)))[0])
        # what the font cannot draw is shown as "?", not left as a blank box that hides the loss
        assert "Judul ?? ok" in text and "isi" in text

    def test_an_empty_digest_still_gives_a_pdf(self, tmp_path):
        md = tmp_path / "d.md"
        md.write_text("", encoding="utf-8")
        assert os.path.exists(render_digest_pdf(str(md)))

    def test_a_failed_render_leaves_no_partial_file(self, tmp_path, monkeypatch):
        md = tmp_path / "d.md"
        md.write_text(DIGEST, encoding="utf-8")
        class DiesHalfWay:
            def __init__(self, filename, **kw):
                self.filename = filename

            def build(self, *a, **kw):
                with open(self.filename, "wb") as f:
                    f.write(b"%PDF-1.4 half")
                raise RuntimeError("boom")

        monkeypatch.setattr("newscrawler.core.newsletter_pdf.SimpleDocTemplate", DiesHalfWay)
        with pytest.raises(RuntimeError):
            render_digest_pdf(str(md))
        assert os.listdir(tmp_path) == ["d.md"]

    def test_a_missing_markdown_raises_instead_of_writing_an_empty_pdf(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            render_digest_pdf(str(tmp_path / "nope.md"))

    def test_a_link_url_with_a_quote_cannot_break_the_markup(self):
        out = inline('[x](https://a.b/c?q="1"&r=2)')
        assert '"1"' not in out.split('href="')[1].split('"')[0]


# ── OPS-41 (#238): page breaks ──────────────────────────────────────────────

def _plain(flowable):
    """Every Paragraph's text inside a flowable (KeepTogether, ListFlowable, Table)."""
    from reportlab.platypus import Paragraph
    if isinstance(flowable, Paragraph):
        return [flowable.getPlainText()]
    out = []
    for attr in ("_content", "_flowables"):
        for child in getattr(flowable, attr, None) or []:
            out += _plain(child)
    for row in getattr(flowable, "_cellvalues", None) or []:
        for cell in row:
            for child in cell if isinstance(cell, list) else [cell]:
                out += _plain(child)
    if hasattr(flowable, "_flowable"):      # a ListItem
        out += _plain(flowable._flowable)
    return out


class TestPageBreaks:
    def test_every_story_is_one_keep_together_with_its_source_and_link_lines(self):
        from reportlab.platypus.flowables import KeepTogether
        from newscrawler.core.newsletter_pdf import build_story
        groups = [_plain(f) for f in build_story(DIGEST) if isinstance(f, KeepTogether)]
        for heading, tail in (("Harga Emas Antam Stagnan", "Artikel terkait: KONTAN"),
                              ("Komisi VIII DPR", "Artikel terkait: TRIBUN")):
            (group,) = [g for g in groups if any(t.startswith(heading) for t in g)]
            assert any(t.startswith("Sumber (") for t in group) and any(t.startswith(tail) for t in group)
            assert any(t.startswith("- ") or "madrasah" in t or "Antam stagnan" in t for t in group)

    def test_every_section_heading_shares_a_keep_together_with_its_first_story(self):
        from reportlab.platypus.flowables import KeepTogether
        from newscrawler.core.newsletter_pdf import build_story
        flow = build_story(DIGEST)
        for section, story in (("Pasar", "Harga Emas Antam"), ("Politik", "Komisi VIII DPR")):
            (group,) = [f for f in flow if isinstance(f, KeepTogether) and section in _plain(f)[0]]
            assert _plain(group)[1].startswith(story)

    def test_a_section_heading_with_no_story_keeps_with_the_line_after_it(self):
        from reportlab.platypus.flowables import KeepTogether
        from newscrawler.core.newsletter_pdf import build_story
        flow = build_story("## Pasar\n\n*…dan 3 berita lainnya di bagian ini.*\n")
        assert len(flow) == 1 and isinstance(flow[0], KeepTogether)
        assert _plain(flow[0]) == ["Pasar", "…dan 3 berita lainnya di bagian ini."]

    def test_no_page_starts_with_a_source_or_link_line_or_ends_on_a_section_heading(self, tmp_path):
        """The 2026-10-04 shape: many stories, each with source and three link lines, over many pages."""
        story = ("### Story {i} with a headline long enough to wrap over the line\n\n"
                 + "".join("- Bullet {i}.%d with enough words to take up a full line of the A4 page body.\n" % k
                           for k in range(4))
                 + "\n**Sumber (3 portal):** KONTAN · CNBC · DETIK\n"
                 + "**Artikel terkait:** [KONTAN: a](https://k.co/{i}) · [CNBC: b](https://c.co/{i}) · "
                   "[DETIK: c](https://d.co/{i}) Secara Mandiri\n\n")
        sections = "".join("## Section %d\n\n" % s + "".join(story.format(i=10 * s + k) for k in range(5)) + "---\n\n"
                           for s in range(8))
        md = tmp_path / "2026-10-04.md"
        md.write_text("# Rangkuman Berita\n\n> Minggu, 4 Oktober 2026 · edisi lengkap\n\n---\n\n" + sections,
                      encoding="utf-8")
        reader = PdfReader(render_digest_pdf(str(md)))
        assert len(reader.pages) > 5
        for number, page in enumerate(reader.pages, 1):
            lines = [l.strip() for l in page.extract_text().splitlines() if l.strip()]
            assert not lines[0].startswith(("Sumber", "Artikel terkait", "Secara Mandiri", "- Bullet", "• Bullet",
                                            "Bullet")), (number, lines[0])
            body = [l for l in lines if not l.startswith("Rangkuman Berita ·")]
            assert not re.fullmatch(r"Section \d+", body[-1]), (number, body[-1])

    def test_the_footer_has_the_indonesian_date_and_the_page_count(self, pdf):
        """SYS-81: 'Rangkuman Berita · Minggu, 4 Okt 2026 · 1/1', never the ISO date."""
        text = _read(pdf)[0]
        assert "Rangkuman Berita · Minggu, 4 Okt 2026 · 1/1" in text and "2026-10-04" not in text


# ── OPS-42 (#242): the phone edition ────────────────────────────────────────

EDITION = """# Rangkuman Berita

> Minggu, 4 Oktober 2026 · ±5 menit baca

## Hari Ini dalam 60 Detik

- Harga emas Antam bertahan di Rp2.574.000 per gram.
- DPR sahkan APBN 2027.
- OPEC+ tahan target produksi minyak November.

## Berita Utama

""" + "".join("""### [Judul berita utama nomor {i} yang cukup panjang](https://lead.co/{i})

Inti berita nomor {i} dalam satu kalimat dua puluh lima kata yang menjelaskan apa yang terjadi siapa dan angka.

- Poin pertama berita {i} memuat fakta baru yang belum ada di inti berita ini.
- Poin kedua berita {i} memuat fakta baru lainnya untuk pembaca.

**Mengapa penting:** Dampaknya bagi pasar disebut oleh narasumber dalam artikel berita {i}.
**Diberitakan {n} portal** · [Baca di Kontan →](https://lead.co/{i})

""".format(i=i, n=11 - i) for i in range(8)) + """## Sekilas

""" + "".join("- **Hukum ·** Sekilas berita nomor %d dalam lima belas kata untuk daftar singkat.\n" % k
              for k in range(15)) + """
---

*Disarikan dari 1.798 artikel di 24 portal. Edisi lengkap memuat 90 berita. Ringkasan ditulis AI dan bisa keliru; cek artikel aslinya untuk detail.*
"""


@pytest.fixture
def edition_pdf(tmp_path):
    from newscrawler.core.newsletter_pdf import render_edition_pdf
    md = tmp_path / "2026-10-04-ringkas.md"
    md.write_text(EDITION, encoding="utf-8")
    return render_edition_pdf(str(md))


def _contrast(foreground, background="#ffffff"):
    from reportlab.lib import colors

    def luminance(color):
        c = colors.toColor(color)
        channels = [v / 1.0 for v in (c.red, c.green, c.blue)]
        linear = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class TestPhoneEdition:
    def test_the_page_is_narrow_and_the_body_is_eleven_and_a_half_points(self, edition_pdf):
        from reportlab.lib.units import mm
        from newscrawler.core.newsletter_pdf import PHONE_PAGE, _phone_styles
        box = PdfReader(edition_pdf).pages[0].mediabox
        # 105 x 228 mm, a phone's ~9:19.5 (owner decision 2026-10-05; the ticket's 190 mm gave a 12-page edition)
        assert (round(float(box.width) / mm), round(float(box.height) / mm)) == (105, 228) == \
            (round(PHONE_PAGE[0] / mm), round(PHONE_PAGE[1] / mm))
        body = _phone_styles()["body"]
        assert (body.fontSize, body.leading) == (11.5, 16)

    def test_a_short_story_is_still_one_block(self):
        from reportlab.platypus.flowables import KeepTogether
        from newscrawler.core.newsletter_pdf import build_edition_story
        md = "## Berita Utama\n\n### [Judul](https://x.co)\n\nInti.\n\n**Diberitakan 2 portal** · [Baca di Kontan →](https://x.co)\n"
        (group,) = [f for f in build_edition_story(md) if isinstance(f, KeepTogether)]
        assert _plain(group)[0] == "BERITA UTAMA" and _plain(group)[-1] == "Baca di Kontan →"

    def test_the_maximal_edition_is_denser_than_one_story_per_page(self, edition_pdf):
        """8 top stories at every word limit and 15 Sekilas lines: 11 pages when a story could not
        break (the first layout); the real 2026-10-04 edition is 7 (EXPERIMENTS.md, OPS-42)."""
        assert len(PdfReader(edition_pdf).pages) <= 8

    def test_no_page_is_only_a_footer(self, edition_pdf):
        """Whole stories move to the next page; that must never leave a page with nothing on it.
        (The page budget, <= 6 for a real day, is measured on replayed editions: EXPERIMENTS.md, OPS-42.)"""
        for page in PdfReader(edition_pdf).pages:
            assert [l for l in page.extract_text().splitlines() if l.strip() and "Rangkuman Berita ·" not in l]

    def test_every_title_is_in_the_text_and_links_to_its_lead_article(self, edition_pdf):
        text, uris = _read(edition_pdf)
        text = _squash(text)
        for i in range(8):
            assert "Judul berita utama nomor %d yang cukup panjang" % i in text
            assert "https://lead.co/%d" % i in uris          # (a title over two lines is two annotations)
        assert set(uris) == {"https://lead.co/%d" % i for i in range(8)}

    def test_the_title_link_is_not_marked_by_colour_alone(self):
        from newscrawler.core.newsletter_pdf import LINK_COLOR, TEXT_COLOR, build_edition_story
        from reportlab.platypus.flowables import KeepTogether
        groups = [f for f in build_edition_story(EDITION) if isinstance(f, KeepTogether)]
        (head,) = [g for g in groups if any("nomor 1 yang" in t for t in _plain(g))]
        (tail,) = [g for g in groups if any("artikel berita 1" in t for t in _plain(g))]
        title = head._content[0]
        (read,) = [f for f in tail._content if hasattr(f, "getPlainText") and "Baca di" in f.getPlainText()]
        assert 'color="%s"' % TEXT_COLOR in title.text and LINK_COLOR not in title.text
        assert 'color="%s"' % LINK_COLOR in read.text and "→" in read.getPlainText()

    def test_one_baca_di_line_per_story(self, edition_pdf):
        text = _squash(_read(edition_pdf)[0])
        assert text.count("Baca di Kontan →") == 8

    def test_the_badge_the_sixty_seconds_and_sekilas_are_there(self, edition_pdf):
        text = _squash(_read(edition_pdf)[0])
        assert "Diberitakan 11 portal" in text and "HARI INI DALAM 60 DETIK" not in text
        assert "Hari Ini dalam 60 Detik" in text and "DPR sahkan APBN 2027." in text
        assert "BERITA UTAMA" in text and "SEKILAS" in text and "Hukum · Sekilas berita nomor 14" in text
        assert "Rangkuman Berita · Minggu, 4 Okt 2026 · 1/" in text

    def test_a_story_breaks_only_after_its_first_sentence_and_never_strands_its_link(self):
        """Owner decision 2026-10-05: a phone story may continue on the next page, but its title
        keeps its first sentence and the 'Baca di' line keeps the line before it."""
        from reportlab.platypus.flowables import KeepTogether
        from newscrawler.core.newsletter_pdf import build_edition_story
        flow = build_edition_story(EDITION)
        groups = [f for f in flow if isinstance(f, KeepTogether)]
        for i in range(8):
            (head,) = [g for g in groups if any("nomor %d yang" % i in t for t in _plain(g))]
            assert any(t.startswith("Inti berita nomor %d" % i) for t in _plain(head))
            (tail,) = [g for g in groups if any("Baca di" in t for t in _plain(g)) and
                       any("artikel berita %d" % i in t for t in _plain(g))]
            assert [t for t in _plain(tail) if t.startswith("Mengapa penting")]
        lead = [g for g in groups if any("nomor 0 yang" in t for t in _plain(g))][0]
        assert _plain(lead)[0] == "BERITA UTAMA"                    # the band stays with the first story
        titles = [f for g in groups for f in g._content if hasattr(f, "style") and "nomor" in f.getPlainText()
                  and "Judul" in f.getPlainText()]
        assert titles[0].style.fontSize == 16 and {t.style.fontSize for t in titles[1:]} == {14}

    def test_every_text_colour_meets_wcag_aa(self):
        from newscrawler.core import newsletter_pdf as p
        styles = list(p._phone_styles().values()) + list(p._styles().values())
        for style in styles:
            assert _contrast(style.textColor) >= 4.5, style.name
        for colour in (p.LINK_COLOR, p.FOOTER_COLOR):
            assert _contrast(colour) >= 4.5, colour
        assert _contrast(p.ACCENT, p.BAND_BG) >= 4.5 and _contrast("#1a1a1a", p.BOX_BG) >= 4.5

    def test_a_sixty_second_heading_without_sentences_is_still_printed(self, tmp_path):
        from newscrawler.core.newsletter_pdf import render_edition_pdf
        md = tmp_path / "e.md"
        md.write_text("# Rangkuman Berita\n\n## Hari Ini dalam 60 Detik\n\n## Berita Utama\n\n### Judul\n\nInti.\n",
                      encoding="utf-8")
        text = _squash(_read(render_edition_pdf(str(md)))[0])
        assert "HARI INI DALAM 60 DETIK" in text and "Judul" in text and "Inti." in text
