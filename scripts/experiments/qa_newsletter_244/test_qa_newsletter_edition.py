"""QA's own test set for tracker #244 (SYS-80..85, OPS-41..43), written from the
tickets' wording, not from the dev's tests. Drives the real chain:
generator -> digest + edition files -> phone/A4 PDF -> Telegram message.

Run from the repo root (5 tests fail by design until SYS-86 #246 and SYS-87 #247 are fixed):
    venv\\Scripts\\python.exe -m pytest scripts/experiments/qa_newsletter_244/test_qa_newsletter_edition.py -q -p no:cacheprovider
"""
import json
import os
import re
import sys
from datetime import date
from unittest.mock import MagicMock

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import newscrawler.core.newsletter_copy as copy  # noqa: E402
import newscrawler.core.newsletter_edition as ne  # noqa: E402
import newscrawler.core.newsletter_generator as ng  # noqa: E402
import newscrawler.core.newsletter_pdf as npdf  # noqa: E402
import newscrawler.core.story_summary as ss  # noqa: E402
from newscrawler.core.constants import SOURCE_AUTHORITY  # noqa: E402
from newscrawler.core.story_summary import StorySummary  # noqa: E402
from newscrawler.domain.entities.extraction.website_name import WebsiteName  # noqa: E402

D = date(2026, 10, 4)
ENGLISH_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
                  "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday")
ENUMS = [w.value for w in WebsiteName]


# ── A scripted LLM that answers like a careful model, per prompt kind ─────────

def _kind(prompt):
    if "Kamu pemimpin redaksi" in prompt:
        return "editor"
    if "Kamu redaktur briefing" in prompt:
        return "story"
    return "group"


def _shown(prompt):
    block = prompt.rsplit("ARTIKEL\n", 1)[1]
    return re.findall(r"^\[(\d+)\] (.+?) — (.*)$", block, re.MULTILINE)


class ScriptedLLM:
    """story: every shown article whose headline contains 'OFFTOPIC' is tidak_terkait;
    the summary is built from the first on-topic headline. editor: the first 6
    summarized ids that satisfy the quotas (computed from the prompt)."""
    name = "qa-model"

    def __init__(self, editor_answer=None):
        self.calls = {"story": 0, "editor": 0, "group": 0}
        self.editor_answer = editor_answer

    def summarize(self, prompt):
        kind = _kind(prompt)
        self.calls[kind] += 1
        if kind == "group":
            n = len(re.findall(r"^\d+: ", prompt, re.MULTILINE))
            return json.dumps({"grup": [[i] for i in range(n)]})
        if kind == "story":
            arts = _shown(prompt)
            on = [int(i) for i, _, h in arts if "OFFTOPIC" not in h]
            off = [int(i) for i, _, h in arts if "OFFTOPIC" in h]
            head = next(h for i, _, h in arts if int(i) in on)
            words = head.split()
            return json.dumps({"judul": " ".join(words[:8]), "inti": head, "poin": [],
                               "mengapa_penting": "", "sekilas": " ".join(words[:12]),
                               "terkait": on, "tidak_terkait": off})
        if self.editor_answer is not None:
            return self.editor_answer(prompt) if callable(self.editor_answer) else self.editor_answer
        return "bukan json"


def _a(sid, topic, cluster, source, headline=None, text=None):
    return {"sitemap_id": sid, "headline": headline or f"Berita {topic} nomor {cluster} versi {sid}",
            "source": source, "category": "news", "link": f"https://{source.lower()}.example/{sid}",
            "posted_at": 20261004, "topic": topic, "l1_text": text or f"Isi berita {topic} {cluster}.",
            "_cluster": cluster}


def _generate(monkeypatch, tmp_path, llm, arts):
    ds = MagicMock()
    ds.save_digest.return_value = 1
    gen = ng.NewsletterGenerator(ds, summarizer=llm, embed_documents=lambda t: [[0.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    monkeypatch.setattr(gen, "_merge_across_sections", lambda entries, vectors: entries)
    by_topic = {}
    for a in arts:
        by_topic.setdefault(a["topic"], []).append(a)
    monkeypatch.setattr(gen, "_encode", lambda texts: [[a["_cluster"]] for a in arts])
    ds.get_articles_for_date.return_value = arts
    path = gen.generate(D)
    return path, ds


SOURCES = ["KONTAN", "INVESTORID", "CNBC", "KOMPAS", "DETIK", "TRIBUN", "ANTARANEWS", "PIKIRANRAKYAT"]


def _big_day():
    """12 sections x 3 clusters; cluster c has (c % 5) + 2 outlets."""
    arts, sid, c = [], 1, 0
    for topic in ng.SECTION_ORDER:
        for _ in range(3):
            for k in range(c % 5 + 2):
                arts.append(_a(sid, topic, c, SOURCES[k]))
                sid += 1
            c += 1
    return arts


# ── SYS-80: tidak_terkait is out of headline, links and portal count ──────────

class TestSYS80EndToEnd:
    def test_offtopic_article_is_absent_from_digest_and_edition(self, monkeypatch, tmp_path):
        arts = [_a(1, "markets", 0, "KONTAN", "Harga emas Antam naik"),
                _a(2, "markets", 0, "CNBC", "Harga emas Antam naik lagi"),
                # TVONENEWS has the highest authority it could have? give it a top-authority outlet instead
                _a(3, "markets", 0, "INVESTORID", "OFFTOPIC Haji Isam punya gerbong saham"),
                _a(4, "law_crime", 1, "KOMPAS", "KPK tahan bupati"), _a(5, "law_crime", 1, "DETIK", "KPK tahan bupati X")]
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), arts)
        digest = open(path, encoding="utf-8").read()
        assert "Haji Isam" not in digest
        assert "investorid.example/3" not in digest
        assert "Diberitakan 2 portal:** Kontan · CNBC Indonesia" in digest or \
               "Diberitakan 2 portal:** CNBC Indonesia · Kontan" in digest
        edition = open(path.edition, encoding="utf-8").read()
        assert "Haji Isam" not in edition and "investorid.example/3" not in edition


# ── SYS-81 / SYS-84: reader text ─────────────────────────────────────────────

class TestReaderText:
    def test_every_month_and_day(self):
        assert [copy.tanggal(date(2026, m, 1)).split()[2] for m in range(1, 13)] == list(copy.MONTHS)
        assert copy.MONTHS == ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
                               "September", "Oktober", "November", "Desember")
        days = {copy.tanggal(date(2026, 10, d)).split(",")[0] for d in range(5, 12)}
        assert days == {"Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"}
        assert copy.tanggal(D) == "Minggu, 4 Oktober 2026"
        assert copy.tanggal_pendek(D) == "Minggu, 4 Okt 2026"

    def test_every_websitename_has_a_brand_and_no_brand_is_an_enum(self):
        for e in ENUMS:
            assert e in copy.OUTLET_NAMES, e
        # a brand identical to the enum is allowed only where that IS the brand (JPNN, VIVA)
        same = sorted(e for e in ENUMS if copy.OUTLET_NAMES[e] == e)
        assert same == ["JPNN", "VIVA"], same

    def test_source_authority_keys_are_real_sources(self):     # SYS-85
        assert set(SOURCE_AUTHORITY) <= set(ENUMS), set(SOURCE_AUTHORITY) - set(ENUMS)
        assert "ANTARANEWS" in SOURCE_AUTHORITY

    def test_generated_files_hold_no_internal_or_english_text(self, monkeypatch, tmp_path):
        llm = ScriptedLLM()
        path, ds = _generate(monkeypatch, tmp_path, llm, _big_day())
        for f in (path, path.edition):
            text = open(f, encoding="utf-8").read()
            for w in ENGLISH_MONTHS:
                assert not re.search(rf"\b{w}\b", text), (f, w)
            assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), f
            assert "qa-model" not in text and "Cluster" not in text and "Ringkasan AI" not in text
            for e in ENUMS:
                if copy.OUTLET_NAMES[e] != e:
                    # the enum may appear inside a URL, never as reader text
                    no_urls = re.sub(r"\]\([^)]*\)", "]", text)
                    for brand in copy.OUTLET_NAMES.values():
                        no_urls = no_urls.replace(brand, "")
                    assert not re.search(rf"\b{e}\b", no_urls), (f, e)

    def test_empty_day(self, monkeypatch, tmp_path):
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), [])
        text = open(path, encoding="utf-8").read()
        assert copy.empty_day(D) in text and "Minggu, 4 Oktober 2026" in text
        assert not os.path.exists(ne.edition_path(path))

    def test_degraded_notice_is_at_the_top(self, monkeypatch, tmp_path):
        class Refuser(ScriptedLLM):
            def summarize(self, prompt):
                if _kind(prompt) == "story":
                    self.calls["story"] += 1
                    return "maaf"
                return super().summarize(prompt)
        path, ds = _generate(monkeypatch, tmp_path, Refuser(), _big_day())
        lines = open(path, encoding="utf-8").read().splitlines()
        notice = [i for i, l in enumerate(lines) if "Sebagian ringkasan tidak tersedia" in l]
        first_section = next(i for i, l in enumerate(lines) if l.startswith("## "))
        assert notice and notice[0] < first_section


# ── SYS-82: guards ───────────────────────────────────────────────────────────

SRC = "Kontan — Pemerintah siapkan Rp15 triliun\nPemerintah menyiapkan anggaran Rp15 triliun untuk 2.574.000 pekerja."


def _ans(**kw):
    d = {"judul": "Pemerintah siapkan anggaran", "inti": "Pemerintah menyiapkan anggaran Rp15 triliun.",
         "poin": [], "mengapa_penting": "", "sekilas": "Anggaran Rp15 triliun disiapkan.",
         "terkait": [0], "tidak_terkait": []}
    d.update(kw)
    return json.dumps(d)


class TestSYS82Guards:
    @pytest.mark.parametrize("field,n,ok", [("judul", 12, True), ("judul", 13, False), ("inti", 25, True),
                                            ("inti", 26, False), ("mengapa_penting", 21, False),
                                            ("sekilas", 15, True), ("sekilas", 16, False)])
    def test_word_limits(self, field, n, ok):
        answer = _ans(**{field: " ".join(["kata"] * n)})
        if ok:
            ss.parse(answer, 1, SRC)
        else:
            with pytest.raises(ss.Rejected) as e:
                ss.parse(answer, 1, SRC)
            assert e.value.reason == "length"

    def test_three_poin_refused_first_try_and_trimmed_on_retry(self):
        answer = _ans(poin=["Satu fakta.", "Dua fakta.", "Tiga fakta."])
        with pytest.raises(ss.Rejected):
            ss.parse(answer, 1, SRC)
        assert ss.parse(answer, 1, SRC, drop_long_poin=True).poin == ["Satu fakta.", "Dua fakta."]

    def test_fenced_json_accepted(self):
        assert ss.parse("```json\n" + _ans() + "\n```", 1, SRC).judul == "Pemerintah siapkan anggaran"

    @pytest.mark.parametrize("terkait,tidak", [([1], [0]), ([0, 0], []), ([0], [0]), ([], [0]), ([True], [])])
    def test_bad_indexes(self, terkait, tidak):
        with pytest.raises(ss.Rejected):
            ss.parse(_ans(terkait=terkait, tidak_terkait=tidak), 1, SRC)

    def test_number_absent_from_articles_refused(self):
        with pytest.raises(ss.Rejected) as e:
            ss.parse(_ans(inti="Pemerintah menyiapkan Rp16 triliun."), 1, SRC)
        assert e.value.reason == "number"

    def test_number_with_other_spacing_accepted(self):
        ss.parse(_ans(inti="Anggaran untuk 2,574,000 pekerja."), 1, SRC)

    def test_decimal_shift_is_a_different_number(self):
        """'Rp1,5 triliun' is a tenth of the articles' 'Rp15 triliun': a number outside the articles."""
        with pytest.raises(ss.Rejected):
            ss.parse(_ans(inti="Pemerintah menyiapkan anggaran Rp1,5 triliun."), 1, SRC)

    def test_retry_then_fallback_counts_both_refusals(self):
        calls = []

        class Bad:
            def summarize(self, prompt):
                calls.append(prompt)
                return "bukan json"
        rej = []
        shown = [{"source": "KONTAN", "headline": "x", "l1_text": "y"}]
        assert ss.summarize_story(Bad(), shown, rej) is None
        assert rej == ["json", "json"] and len(calls) == 2 and "ditolak" in calls[1]


# ── SYS-83: edition rules and the echo guard ─────────────────────────────────

def _cand(cid, topic, judul, inti, sekilas, portals=5, guaranteed=False):
    st = StorySummary(judul, inti, [], "", sekilas, [0], [])
    return ne.Candidate(cid, topic, {"story": st, "sources": [f"S{i}" for i in range(portals)], "links": [],
                                     "source_text": inti}, guaranteed)


# (top story, a Sekilas candidate about a DIFFERENT event) -- judul/inti of the tops are verbatim from the
# 2026-09-28/10-03/10-04 replay digests; the Sekilas lines are realistic <= 15-word lines for distinct stories
# from the same digests.
DISTINCT = [
    (("politics_government", "Prabowo perintahkan audit forensik keuangan haji BPKH",
      "Presiden Prabowo Subianto memerintahkan audit forensik tata kelola keuangan haji yang dikelola BPKH, "
      "menurut Wamenhaj Dahnil Anzar Simanjuntak."),
     ("politics_government", "Presiden Prabowo berhentikan sementara Wagub Babel Hellyana",
      "Presiden Prabowo Subianto memberhentikan sementara Wagub Bangka Belitung Hellyana.")),
    (("macro_policy", "Pemerintah salurkan BSU Rp900.000 ke 13,3 juta pekerja",
      "Pemerintah menyalurkan Bantuan Subsidi Upah Rp900.000 per pekerja untuk periode Oktober-Desember 2026 "
      "dengan anggaran Rp12 triliun."),
     ("consumer", "Penjualan rumah subsidi turun, pengembang minta bantuan pemerintah",
      "Penjualan rumah subsidi anjlok, pengembang minta bantuan pemerintah.")),
    (("macro_policy", "LPS bayar klaim simpanan Rp243,02 miliar nasabah empat BPR Jabar",
      "LPS membayarkan Rp243,02 miliar klaim penjaminan simpanan nasabah empat BPR/BPRS di Jawa Barat yang "
      "izin usahanya dicabut."),
     ("politics_government", "Proyek data center AI Jatiluhur dihentikan sementara karena izin belum rampung",
      "Gubernur Jawa Barat hentikan proyek data center di Jatiluhur karena izin belum lengkap.")),
    (("corporate", "Proyek data center AI Rp3,5 triliun di Jatiluhur disetop",
      "Gubernur Jawa Barat Dedi Mulyadi menghentikan sementara proyek data center AI BDx Data Centers senilai "
      "Rp3,5 triliun di Jatiluhur, Purwakarta."),
     ("corporate", "EJIF 2026 hasilkan komitmen investasi Rp2,4 triliun di Jatim",
      "EJIF 2026 di Jawa Timur hasilkan komitmen investasi senilai Rp2,4 triliun.")),
]


class TestSYS83EchoGuard:
    @pytest.mark.parametrize("top,other", DISTINCT, ids=["prabowo", "subsidi", "jawa-barat", "jawa-timur"])
    def test_a_distinct_event_is_not_hidden(self, top, other):
        t = _cand(1, top[0], top[1], top[2], "")
        c = _cand(2, other[0], other[1], "", other[2])
        assert not ne.echoes(c, t), sorted(set(ne.content_words(f"{c.story.judul}. {c.story.sekilas}"))
                                          & set(ne.content_words(f"{t.story.judul}. {t.story.inti}")))

    def test_a_true_repeat_is_hidden(self):
        t = _cand(1, "international", "Trump tolak proposal damai Iran, harga minyak dunia naik",
                  "Presiden AS Donald Trump menolak proposal damai Iran sehingga harga minyak dunia naik.", "")
        c = _cand(2, "international", "Iran tegaskan diplomasi, Trump tolak proposal damai",
                  "", "Trump menolak proposal damai Iran meski Teheran tegaskan jalur diplomasi.")
        assert ne.echoes(c, t)


class TestSYS83Edition:
    def _edition(self, monkeypatch, tmp_path, editor=None):
        llm = ScriptedLLM(editor)
        path, ds = _generate(monkeypatch, tmp_path, llm, _big_day())
        return path, ds, llm

    def test_files_stats_and_budget(self, monkeypatch, tmp_path):
        path, ds, llm = self._edition(monkeypatch, tmp_path)
        assert path.edition == os.path.join(str(tmp_path), "2026-10-04-ringkas.md")
        cats = ds.save_digest.call_args.kwargs["categories"]
        ed = cats["_edition"]
        assert ed["built"] and ed["editor_fallback"] and 6 <= ed["utama"] <= 8
        text = open(path.edition, encoding="utf-8").read()
        assert ne.reader_words(text) == ed["words"] <= 1200
        # one LLM editor call + one retry, no extra summary calls
        assert llm.calls["editor"] == 2 and llm.calls["story"] == 36

    def test_fallback_respects_quotas(self, monkeypatch, tmp_path):
        path, ds, llm = self._edition(monkeypatch, tmp_path)
        text = open(path.edition, encoding="utf-8").read()
        top = text.split("## Berita Utama")[1].split("## Sekilas")[0]
        titles = re.findall(r"^### \[(.*?)\]", top, re.MULTILINE)
        topics = [re.search(r"Berita (\w+) nomor", t).group(1) for t in titles]
        assert all(topics.count(t) <= 2 for t in topics)
        non_fin = [t for t in topics if t not in ng.TOPICS_FINANCE]
        assert len(non_fin) >= 2
        # the 60-second block: 3-5 sentences about different top stories
        sixty = text.split("## Hari Ini dalam 60 Detik")[1].split("## Berita Utama")[0]
        assert 3 <= len(re.findall(r"^- ", sixty, re.MULTILINE)) <= 5

    def test_one_baca_di_per_top_story_and_title_links_to_it(self, monkeypatch, tmp_path):
        path, ds, llm = self._edition(monkeypatch, tmp_path)
        text = open(path.edition, encoding="utf-8").read()
        stories = text.split("## Berita Utama")[1].split("## Sekilas")[0].split("\n### ")[1:]
        for s in stories:
            assert s.count("Baca di ") == 1
            title_url = re.match(r"\[.*?\]\((.*?)\)", s).group(1)
            read_url = re.search(r"\[Baca di [^\]]*→\]\((.*?)\)", s).group(1)
            assert title_url == read_url

    def test_full_digest_unchanged_in_scope(self, monkeypatch, tmp_path):
        path, ds, llm = self._edition(monkeypatch, tmp_path)
        digest = open(path, encoding="utf-8").read()
        assert digest.count("\n### ") == 36
        assert len(re.findall(r"^## ", digest, re.MULTILINE)) == 12


# ── OPS-41 / OPS-42: PDFs ────────────────────────────────────────────────────

def _contrast(hex_fg, hex_bg="#ffffff"):
    def lum(h):
        h = h.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    a, b = sorted((lum(hex_fg), lum(hex_bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class TestPDF:
    @pytest.fixture
    def files(self, monkeypatch, tmp_path):
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), _big_day())
        return path, npdf.render_edition_pdf(path.edition), npdf.render_digest_pdf(path)

    def test_phone_pdf(self, files):
        from pypdf import PdfReader
        path, phone, a4 = files
        r = PdfReader(phone)
        box = r.pages[0].mediabox
        assert (round(float(box.width) / 72 * 25.4), round(float(box.height) / 72 * 25.4)) == (105, 228)
        text = "\n".join(p.extract_text() for p in r.pages)
        md = open(path.edition, encoding="utf-8").read()
        for title in re.findall(r"^### \[(.*?)\]", md, re.MULTILINE):
            assert " ".join(title.split()[:4]) in " ".join(text.split())
        links = [a.get_object()["/A"]["/URI"] for p in r.pages for a in (p.get("/Annots") or [])
                 if a.get_object().get("/Subtype") == "/Link"]
        utama = md.count("\n### ")
        assert len(set(links)) == utama and len(links) >= 2 * utama   # a wrapped title is one annotation per line
        assert "Rangkuman Berita · Minggu, 4 Okt 2026 · 1/" in text
        assert "?" not in text.replace("?page", "")    # no glyph-less character

    def test_no_page_starts_with_a_link_line_or_ends_on_a_section(self, files):
        from pypdf import PdfReader
        path, phone, a4 = files
        for pdf in (phone, a4):
            for page in PdfReader(pdf).pages:
                lines = [l for l in page.extract_text().splitlines() if l.strip()]
                body = [l for l in lines if "Rangkuman Berita ·" not in l]
                assert not body[0].startswith(("Baca di", "Artikel terkait", "Diberitakan")), (pdf, body[0])
                assert body[-1].strip().upper() not in {n.upper() for n in copy.SECTION_NAMES.values()} | \
                    {copy.AT_A_GLANCE.upper(), copy.TOP_STORIES.upper()}, (pdf, body[-1])

    @pytest.mark.parametrize("fg,bg", [(npdf.LINK_COLOR, "#ffffff"), (npdf.FOOTER_COLOR, "#ffffff"),
                                       (npdf.ACCENT, npdf.BAND_BG), (npdf.TEXT_COLOR, npdf.BOX_BG),
                                       ("#555555", "#ffffff"), ("#444444", "#ffffff"), (npdf.ACCENT, npdf.BOX_BG)])
    def test_contrast_on_its_actual_background(self, fg, bg):
        assert _contrast(fg, bg) >= 4.5

    def test_special_characters_render(self, tmp_path):
        md = ("# Rangkuman Berita\n\n> Minggu, 4 Oktober 2026 · ±5 menit baca\n\n## Berita Utama\n\n"
              "### [S&P 500 <naik> 2% *hari* ini](https://x.example/a?b=1&c=2)\n\nIndeks S&P 500 naik <2%> & ditutup.\n\n"
              "**Diberitakan 3 portal** · [Baca di Kontan →](https://x.example/a?b=1&c=2)\n")
        f = tmp_path / "2026-10-04-ringkas.md"
        f.write_text(md, encoding="utf-8")
        from pypdf import PdfReader
        text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(npdf.render_edition_pdf(str(f))).pages)
        assert "S&P 500 <naik> 2%" in text and "naik <2%> & ditutup" in text


# ── OPS-43: Telegram ─────────────────────────────────────────────────────────

class TestOPS43:
    def test_message_from_a_generated_edition(self, monkeypatch, tmp_path):
        import run_scheduled_newsletter as rsn
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), _big_day())
        sentences, top = ne.briefing(open(path.edition, encoding="utf-8").read())
        msg = rsn.edition_message(D, sentences, top)
        assert msg.startswith("<b>Rangkuman Berita</b> · Minggu, 4 Okt 2026 (±5 menit)")
        assert msg.count("\n• ") == len(sentences) and 3 <= len(sentences) <= 5
        assert msg.endswith(f"Buka PDF untuk {top} berita utama dan sekilas lainnya.")
        assert len(msg) <= 4096

    def test_html_is_escaped(self):
        import run_scheduled_newsletter as rsn
        msg = rsn.edition_message(D, ["S&P <500> naik"], 6)
        assert "S&amp;P &lt;500&gt; naik" in msg

    def test_normal_day_sends_message_then_edition_pdf_never_the_digest(self, monkeypatch, tmp_path):
        import run_scheduled_newsletter as rsn
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), _big_day())
        sent = []
        monkeypatch.setattr(rsn, "_send_message", lambda text: sent.append(("msg", text)) or True)
        monkeypatch.setattr(rsn, "_send_pdf_file", lambda d, p: sent.append(("pdf", p)) or True)
        monkeypatch.setattr(rsn, "_notify", lambda m: sent.append(("op", m)))
        rsn._deliver(D, str(path), path.edition, MagicMock(categories={}))
        assert [k for k, _ in sent] == ["msg", "pdf"]
        assert sent[1][1].endswith("2026-10-04-ringkas.pdf")

    def test_pdf_render_failure_says_so_in_the_message(self, monkeypatch, tmp_path):
        import run_scheduled_newsletter as rsn
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), _big_day())
        sent = []
        monkeypatch.setattr(rsn, "_send_message", lambda text: sent.append(("msg", text)) or True)
        monkeypatch.setattr(rsn, "_send_pdf_file", lambda d, p: sent.append(("pdf", p)) or True)
        monkeypatch.setattr(rsn, "_notify", lambda m: sent.append(("op", m)))
        monkeypatch.setattr(npdf, "render_edition_pdf", MagicMock(side_effect=RuntimeError("boom")))
        rsn._deliver(D, str(path), path.edition, MagicMock(categories={}))
        msgs = [t for k, t in sent if k == "msg"]
        assert msgs and msgs[0].endswith(copy.MESSAGE_NO_PDF) and "pdf" not in [k for k, _ in sent]

    def test_no_edition_sends_notice_and_digest_pdf(self, monkeypatch, tmp_path):
        import run_scheduled_newsletter as rsn
        path, ds = _generate(monkeypatch, tmp_path, ScriptedLLM(), _big_day())
        sent = []
        monkeypatch.setattr(rsn, "_send_message", lambda text: sent.append(("msg", text)) or True)
        monkeypatch.setattr(rsn, "_send_pdf_file", lambda d, p: sent.append(("pdf", p)) or True)
        row = MagicMock(categories={"_summaries": {"total": 36, "summarized": 30}})
        rsn._deliver(D, str(path), None, row)
        assert copy.MESSAGE_NO_EDITION in sent[0][1] and "6 berita hanya ditampilkan judulnya" in sent[0][1]
        assert sent[1][1].endswith("2026-10-04.pdf")
