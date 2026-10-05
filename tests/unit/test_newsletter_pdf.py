"""OPS-40 (#235): a digest becomes a PDF that holds what the markdown holds.

The tests read the PDF back (text and link annotations) and compare it with the
markdown, so a renderer that drops a story, a link or the spaces between links
fails here -- not only one that crashes.
"""
import os
import re

import pytest
from pypdf import PdfReader

from newscrawler.core.newsletter_pdf import inline, render_digest_pdf, strip_emoji

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
