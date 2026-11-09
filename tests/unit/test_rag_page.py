"""The rendered search page and its fragments (tracker #272).

SYS-93: the answer is escaped; citations link only to cards that exist.
SYS-94: a failed model shows a state, never the exception.
SYS-95: reader names and Indonesian dates; no internal source name, yyyymmdd, chunk or timing.
SYS-96: every control has a label; buttons have names.
SYS-97: follow-ups append to a thread with the session; the search box starts a new one.
SYS-101: no literal reader text in the templates; every state renders its exact copy.
"""
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import newscrawler.web.app as app_mod
from newscrawler.core import web_copy as copy
from newscrawler.core.newsletter_copy import MONTHS, OUTLET_NAMES
from newscrawler.core.summarizer import Reply
from newscrawler.web import answer as answer_text
from newscrawler.web.query_processor import FAILED, NO_HITS, OK, UNAVAILABLE, AnswerResult
from newscrawler.web.session_manager import SessionManager
from newscrawler.web.site_stats import SiteStats
from newscrawler.web.turn_store import TurnStore

TEMPLATES = Path(app_mod.__file__).parent / "templates"
# Spellings Indonesian does not share (April, September, November are the same in both).
ENGLISH_MONTHS = ("January", "February", "March", "May", "June", "July", "August", "October", "December",
                  "Oct", "Aug", "Dec")

HITS = [
    {"n": 1, "sitemap_id": 11, "source": "KONTAN", "posted_at": 20261005, "posted_date": date(2026, 10, 5),
     "title": "Rupiah Melemah ke Rp16.420", "link": "https://www.kontan.co.id/news/rupiah",
     "topic": "markets", "text_content": "Rupiah ditutup melemah ke Rp16.420 per dolar AS."},
    {"n": 2, "sitemap_id": 12, "source": "CNBC", "posted_at": 20261002, "posted_date": date(2026, 10, 2),
     "title": "Asing Jual <b>Saham</b>", "link": "javascript:alert(1)",
     "topic": "corporate", "text_content": "Asing jual bersih Rp1,2 triliun."},
]


class FakeProcessor:
    def __init__(self):
        self.hits = [dict(h) for h in HITS]
        self.result = AnswerResult(OK, "Jawaban [1].", answer_text.parse("Jawaban [1].", 2))
        self.retrieved = []
        self.histories = []
        self.retrieval_histories = []

    def retrieve(self, question, filters=None, today=None, history=()):
        self.retrieved.append((question, filters))
        self.retrieval_histories.append(list(history))
        return [dict(h) for h in self.hits]

    def answer(self, question, hits, history, today=None):
        self.histories.append(list(history))
        return self.result


@pytest.fixture
def page(monkeypatch):
    fake = FakeProcessor()
    monkeypatch.setattr(app_mod, "_get_processor", lambda: fake)
    monkeypatch.setattr(app_mod, "_refresh_faiss_if_stale", lambda: None)
    stats = SiteStats(95736, 29, datetime(2026, 10, 7, 20, 16), (("CNBC", "CNBC Indonesia"), ("KONTAN", "Kontan")))
    monkeypatch.setattr(app_mod, "_get_site_stats", lambda: SimpleNamespace(get=lambda: stats))
    monkeypatch.setattr(app_mod, "_turns", TurnStore())
    monkeypatch.setattr(app_mod, "_sessions", SessionManager())
    return TestClient(app_mod.app), fake


def _ask(client, question="Kenapa rupiah melemah?", **form):
    return client.post("/api/query/form", data={"query": question, **form}, headers={"HX-Request": "true"})


def _turn_id(html):
    return re.search(r'hx-post="/api/answer/([0-9a-f]+)"', html).group(1)


def _answer(client, turn_id):
    return client.post(f"/api/answer/{turn_id}", headers={"HX-Request": "true"}).text


def _visible_text(html):
    """Text nodes plus attributes a reader sees or hears; `value` and `href` excluded."""
    out = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            out.extend(v for k, v in attrs if k in ("placeholder", "aria-label", "title", "alt") and v)

        def handle_data(self, data):
            out.append(data)
    P().feed(re.sub(r"<script.*?</script>", "", html, flags=re.S))
    return " ".join(out)


def _reader_leaks(html):
    text = _visible_text(html)
    # Some brands contain their source name ("CNBC Indonesia", "JPNN", "VIVA"): look for internal
    # names in what is left once every brand name is taken out.
    bare = text
    for brand in sorted(OUTLET_NAMES.values(), key=len, reverse=True):
        bare = bare.replace(brand, " ")
    leaks = [name for name in OUTLET_NAMES if re.search(rf"\b{name}\b", bare)]
    leaks += re.findall(r"\b20\d{6}\b", text)
    leaks += [m for m in ENGLISH_MONTHS if re.search(rf"\b{m}\b", text)]
    leaks += [w for w in ("chunk", "query", "RAG", "konteks", "ms") if re.search(rf"\b{w}\b", text, re.I)]
    return leaks


class TestIndex:
    def test_title_hero_and_corpus_line(self, page):
        client, _ = page
        html = client.get("/").text
        assert f"<title>{copy.PAGE_TITLE}</title>" in html
        assert "Jawaban disusun dari 95.736 artikel di 29 portal berita" in html
        assert "pukul 20.16 WIB" in html
        assert "NewsAggregator Search" not in html and "berita ekonomi" not in html

    def test_topic_options_are_the_rubric_topics_with_section_names(self, page):
        client, _ = page
        html = client.get("/").text
        select = re.search(r'<select id="filter-topic".*?</select>', html, re.S).group(0)
        values = re.findall(r'<option value="([^"]*)"', select)
        assert values[1:] == list(app_mod.web_filters.TOPIC_CHOICES)
        assert ">Pasar<" in select and ">Hukum &amp; Kriminal<" in select

    def test_portals_by_brand_name_internal_name_only_as_value(self, page):
        client, _ = page
        html = client.get("/").text
        assert '<option value="KONTAN">Kontan</option>' in html
        assert _reader_leaks(html) == []

    def test_every_control_is_labelled_and_every_button_named(self, page):
        client, _ = page
        _assert_labelled(client.get("/").text)

    def test_the_search_form_starts_a_new_conversation(self, page):
        client, _ = page
        form = re.search(r'<form class="search" id="search-form".*?</form>', client.get("/").text, re.S).group(0)
        assert 'name="session_id"' not in form, "SYS-97: the search box must never carry the old session"
        assert 'hx-swap="innerHTML"' in form and 'hx-target="#thread"' in form

    def test_no_english_months_or_internal_names(self, page):
        client, _ = page
        assert _reader_leaks(client.get("/").text) == []

    def test_the_page_runs_without_a_cdn(self, page):
        html = page[0].get("/").text
        assert 'src="/static/htmx.min.js"' in html and "unpkg.com" not in html


class TestTurn:
    def test_sources_render_with_reader_names_and_dates(self, page):
        client, _ = page
        html = _ask(client).text
        assert "Berdasarkan 2 artikel" in html
        assert "Kontan" in html and "Senin, 5 Okt 2026" in html and ">Pasar<" in html
        assert "Baca di Kontan →" in html
        assert _reader_leaks(html) == []

    def test_scraped_text_is_escaped_and_a_non_http_link_is_dropped(self, page):
        client, _ = page
        html = _ask(client).text
        assert "Asing Jual &lt;b&gt;Saham&lt;/b&gt;" in html
        assert "javascript:" not in html

    def test_the_answer_is_requested_in_a_second_step(self, page):
        client, fake = page
        html = _ask(client).text
        assert 'hx-trigger="load"' in html and copy.LOADING_ANSWER.format(n=2) in html
        assert fake.histories == [], "step one must not call the model"

    def test_the_follow_up_form_carries_the_session_and_appends(self, page):
        client, _ = page
        html = _ask(client).text
        form = re.search(r'<form id="followup".*?</form>', html, re.S).group(0)
        assert 'hx-swap-oob="true"' in form and 'hx-swap="beforeend"' in form
        sid = re.search(r'name="session_id" value="([^"]+)"', form).group(1)
        html2 = _ask(client, "Lalu?", session_id=sid).text
        assert f'name="session_id" value="{sid}"' in html2
        _assert_labelled(html)

    def test_no_hits_no_filters(self, page):
        client, fake = page
        fake.hits = []
        html = _ask(client).text
        assert copy.NO_HITS in html and "/api/answer/" not in html

    def test_no_hits_with_filters_names_them_and_offers_to_clear(self, page):
        client, fake = page
        fake.hits = []
        html = _ask(client, topic="markets", source="KONTAN", rentang="7").text
        assert "Tidak ada artikel Pasar dari Kontan dalam 7 hari terakhir." in html
        assert copy.CLEAR_FILTERS in html and "data-clear-filters" in html

    def test_active_filters_show_as_removable_chips(self, page):
        client, _ = page
        html = _ask(client, topic="law_crime", rentang="30").text
        chips = re.search(r'<ul class="active-filters".*?</ul>', html, re.S).group(0)
        assert 'hx-swap-oob="true"' in chips
        assert 'data-remove-filter="topic"' in chips and "Hukum &amp; Kriminal" in chips
        assert 'aria-label="Hapus filter 30 hari terakhir"' in chips

    def test_the_filters_reach_retrieval(self, page):
        client, fake = page
        _ask(client, topic="markets", source="KONTAN", rentang="30")
        filters = fake.retrieved[-1][1]
        assert (filters.topic, filters.source, filters.days) == ("markets", "KONTAN", 30)

    @pytest.mark.parametrize("question, notice", [("   ", copy.QUESTION_EMPTY),
                                                   ("x" * 501, copy.QUESTION_TOO_LONG.format(n=500))])
    def test_a_bad_question_is_refused_without_searching(self, page, question, notice):
        client, fake = page
        html = _ask(client, question).text
        assert notice in html and fake.retrieved == []

    def test_a_question_of_exactly_the_maximum_is_asked(self, page, monkeypatch):
        """DBT-62: RAG_QUESTION_MAX_CHARS is the longest allowed, not the shortest refused."""
        client, fake = page
        html = _ask(client, "x" * 500).text
        assert copy.QUESTION_TOO_LONG.format(n=500) not in html and fake.retrieved[-1][0] == "x" * 500
        monkeypatch.setattr(app_mod, "_run_query", lambda **k: {"answer_status": OK, "answer": "",
                                                                "numbers_unverified": False, "sources": []})
        assert client.post("/api/query", json={"query": "x" * 500}).status_code == 200

    def test_card_links_open_a_new_tab_without_the_opener(self, page):
        """DBT-62 / security review S3: a scraped site opened from a card cannot reach this page."""
        html = _ask(page[0]).text
        links = re.findall(r'<a class="card-link"[^>]*>', html)
        assert links and all('target="_blank"' in a and 'rel="noopener noreferrer"' in a for a in links)

    def test_the_follow_up_form_sends_the_active_filters(self, page):
        """DBT-62: a follow-up searches with the filters its chips show, so the form includes every
        filter control of the page."""
        form = re.search(r'<form id="followup".*?</form>', _ask(page[0]).text, re.S).group(0)
        include = re.search(r'hx-include="([^"]+)"', form).group(1)
        assert [s.strip() for s in include.split(",")] == [
            "#filter-topic", "#filter-source", "[name='rentang']", "#filter-from", "#filter-to"]
        index = page[0].get("/").text
        for control in ('id="filter-topic"', 'id="filter-source"', 'name="rentang"', 'id="filter-from"',
                        'id="filter-to"'):
            assert control in index


class TestAnswer:
    def _answer_html(self, page, result):
        client, fake = page
        fake.result = result
        return _answer(client, _turn_id(_ask(client).text))

    def test_markup_in_the_answer_is_shown_as_text(self, page):
        raw = 'Jawaban <img src=x onerror=alert(1)> dan <b>x</b> [1].'
        html = self._answer_html(page, AnswerResult(OK, raw, answer_text.parse(raw, 2)))
        assert "<img" not in html and "<b>x</b>" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html and "&lt;b&gt;x&lt;/b&gt;" in html

    def test_citations_link_to_cards_and_out_of_range_stays_text(self, page):
        client, fake = page
        raw = "Fakta [2] dan [9]."
        fake.result = AnswerResult(OK, raw, answer_text.parse(raw, 2))
        turn_id = _turn_id(_ask(client).text)
        html = _answer(client, turn_id)
        assert f'href="#src-{turn_id}-2"' in html and 'aria-label="Sumber 2"' in html
        assert "[9]" in html and f"#src-{turn_id}-9" not in html

    def test_ok_answer_has_the_disclosure(self, page):
        html = self._answer_html(page, AnswerResult(OK, "Jawaban [1].", answer_text.parse("Jawaban [1].", 2)))
        assert copy.DISCLOSURE in html and copy.UNVERIFIED not in html

    def test_an_unverified_number_shows_the_warning(self, page):
        html = self._answer_html(page, AnswerResult(OK, "Rp9 [1]", answer_text.parse("Rp9 [1]", 2), unverified="9"))
        assert copy.UNVERIFIED in html

    def test_unavailable_copy(self, page):
        html = self._answer_html(page, AnswerResult(UNAVAILABLE))
        assert copy.UNAVAILABLE in html and _reader_leaks(html) == []

    def test_failed_offers_a_retry_of_the_same_turn(self, page):
        client, fake = page
        fake.result = AnswerResult(FAILED)
        turn_id = _turn_id(_ask(client).text)
        html = _answer(client, turn_id)
        assert copy.FAILED in html and copy.RETRY in html
        assert f'hx-post="/api/answer/{turn_id}"' in html
        fake.result = AnswerResult(OK, "Jawaban.", answer_text.parse("Jawaban.", 2))
        assert copy.DISCLOSURE in _answer(client, turn_id), "the retry must find its turn"

    def test_a_final_answer_releases_the_turn(self, page):
        client, _ = page
        turn_id = _turn_id(_ask(client).text)
        _answer(client, turn_id)
        assert copy.EXPIRED in _answer(client, turn_id)

    def test_an_unknown_turn_is_expired(self, page):
        assert copy.EXPIRED in _answer(page[0], "deadbeef")


class TestConversation:
    def test_a_follow_up_is_sent_with_the_previous_answer(self, page):
        client, fake = page
        html = _ask(client, "Kenapa rupiah melemah?").text
        _answer(client, _turn_id(html))
        sid = re.search(r'name="session_id" value="([^"]+)"', html).group(1)
        _answer(client, _turn_id(_ask(client, "Lalu apa kata BI?", session_id=sid).text))
        assert fake.histories[0] == []
        assert [t["question"] for t in fake.histories[1]] == ["Kenapa rupiah melemah?"]

    def test_a_follow_up_is_retrieved_with_the_conversation(self, page):
        """SYS-104 (#274): the thread reaches retrieval, not only the answer prompt."""
        client, fake = page
        html = _ask(client, "Apa kata OJK soal kredit perbankan?").text
        _answer(client, _turn_id(html))
        sid = re.search(r'name="session_id" value="([^"]+)"', html).group(1)
        _ask(client, "Berapa target pertumbuhannya tahun depan?", session_id=sid)
        assert fake.retrieval_histories[0] == []
        assert [t["question"] for t in fake.retrieval_histories[1]] == ["Apa kata OJK soal kredit perbankan?"]

    def test_a_follow_up_keeps_its_thread_when_the_answer_failed(self, page):
        """SYS-104: only an ok answer enters the prompt's history (SYS-97), but the thread for
        retrieval is every question asked: with the provider down (2026-10-08: the key was blocked)
        a follow-up still finds its subject."""
        client, fake = page
        fake.result = AnswerResult(FAILED)
        html = _ask(client, "Apa kata OJK soal kredit perbankan?").text
        _answer(client, _turn_id(html))
        sid = re.search(r'name="session_id" value="([^"]+)"', html).group(1)
        _answer(client, _turn_id(_ask(client, "Berapa target pertumbuhannya tahun depan?", session_id=sid).text))
        assert [t["question"] for t in fake.retrieval_histories[1]] == ["Apa kata OJK soal kredit perbankan?"]
        assert fake.histories[-1] == [], "the prompt still gets answered turns only"

    def test_the_json_api_retrieves_a_follow_up_with_its_thread(self, page, monkeypatch):
        client, _ = page
        calls = []
        monkeypatch.setattr(app_mod, "_run_query", lambda **k: calls.append(k) or {
            "answer_status": FAILED, "answer": "", "numbers_unverified": False, "sources": []})
        sid = client.post("/api/query", json={"query": "Apa kata OJK soal kredit perbankan?"}).json()["session_id"]
        client.post("/api/query", json={"query": "Berapa targetnya?", "session_id": sid})
        assert calls[0]["thread"] == [] and calls[1]["session_history"] == []
        assert calls[1]["thread"] == [{"question": "Apa kata OJK soal kredit perbankan?"}]

    def test_a_new_question_from_the_search_box_has_no_history(self, page):
        client, fake = page
        _answer(client, _turn_id(_ask(client, "Pertama").text))
        _answer(client, _turn_id(_ask(client, "Tidak berkaitan").text))   # no session_id: "Pertanyaan baru"
        assert fake.histories == [[], []]
        assert fake.retrieval_histories == [[], []], "the search box retrieves on its own text"

    def test_a_failed_answer_is_not_history(self, page):
        client, fake = page
        fake.result = AnswerResult(FAILED)
        html = _ask(client).text
        _answer(client, _turn_id(html))
        sid = re.search(r'name="session_id" value="([^"]+)"', html).group(1)
        fake.result = AnswerResult(OK, "x", answer_text.parse("x", 2))
        _answer(client, _turn_id(_ask(client, "Lalu?", session_id=sid).text))
        assert fake.histories[-1] == []


class TestJsonApi:
    def test_one_call_returns_state_and_sources(self, page, monkeypatch):
        client, fake = page
        monkeypatch.setattr(app_mod, "_run_query", lambda **k: {"answer_status": OK, "answer": "Jawaban [1].",
                                                                "numbers_unverified": False, "sources": []})
        out = client.post("/api/query", json={"query": "q", "topic": "markets"}).json()
        assert out["answer_status"] == OK and out["session_id"]

    def test_a_too_long_question_is_422(self, page):
        assert page[0].post("/api/query", json={"query": "x" * 501}).status_code == 422


class TestTemplates:
    def test_no_template_turns_off_escaping(self):
        for path in TEMPLATES.glob("*.html"):
            source = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
            assert not re.search(r"\|\s*safe\b|Markup\(|autoescape\s+false", source), \
                f"{path.name} renders a value unescaped"

    def test_no_literal_reader_text_in_templates(self):
        for path in TEMPLATES.glob("*.html"):
            source = path.read_text(encoding="utf-8")
            source = re.sub(r"\{#.*?#\}", "", source, flags=re.S)
            source = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "", source, flags=re.S)
            source = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", source, flags=re.S)
            words = re.findall(r"[A-Za-z]{2,}", _visible_text(source))
            assert words == [], f"{path.name} has literal reader text: {words[:10]}"

    def test_the_old_fragment_is_gone(self):
        assert not (TEMPLATES / "result_fragment.html").exists()


class TestCopyFormatters:
    def test_kapan(self):
        today = date(2026, 10, 7)
        assert copy.kapan(datetime(2026, 10, 7, 9, 5), today) == "pukul 09.05 WIB"
        assert copy.kapan(datetime(2026, 10, 6, 20, 16), today) == "Selasa, 6 Okt 2026 pukul 20.16 WIB"

    def test_hero_without_stats_has_no_zero(self):
        assert copy.hero_line(None, None, None, date(2026, 10, 7)) == copy.HERO_LINE_NO_STATS
        assert copy.hero_line(0, 0, datetime(2026, 10, 7), date(2026, 10, 7)) == copy.HERO_LINE_NO_STATS

    def test_range_chip(self):
        assert copy.range_chip(None, date(2026, 10, 1), date(2026, 10, 5)) == "1 Okt 2026 – 5 Okt 2026"
        assert copy.range_chip(None, date(2026, 10, 1), None) == "Sejak 1 Okt 2026"
        assert copy.range_chip(None, None, date(2026, 10, 5)) == "Hingga 5 Okt 2026"

    def test_every_copy_string_is_indonesian(self):
        strings = [v for k, v in vars(copy).items() if k.isupper() and isinstance(v, str)]
        strings += list(copy.EXAMPLES)
        for s in strings:
            assert not re.search(r"\b(the|and|query|chunk|RAG|answer|source)\b", s, re.I), s
            assert not any(m in s for m in ENGLISH_MONTHS), s


def _assert_labelled(html):
    """SYS-96: every visible input/select has a <label for>, or sits in a <label>, or has an
    aria-label; every button has text or an aria-label."""
    labels_for = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    for m in re.finditer(r"<(input|select)\b([^>]*)>", html):
        attrs = m.group(2)
        if 'type="hidden"' in attrs:
            continue
        control_id = re.search(r'\bid="([^"]+)"', attrs)
        in_label = html.rfind("<label", 0, m.start()) > html.rfind("</label>", 0, m.start())
        assert in_label or "aria-label=" in attrs or (control_id and control_id.group(1) in labels_for), \
            f"unlabelled control: {m.group(0)}"
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", html, re.S):
        name = re.sub(r"<[^>]+>|\{\{.*?\}\}", "", m.group(2)).strip()
        assert name or "aria-label=" in m.group(1), f"unnamed button: {m.group(0)[:120]}"
        assert name not in ("→", "&#x2192;"), "a button named only by an arrow"


def test_months_table_is_indonesian():
    assert MONTHS[9] == "Oktober"


class TestWarmUp:
    """SYS-102: the model and FAISS load when the app starts, not on the first question."""

    def test_start_up_warms_the_processor_in_the_background(self, monkeypatch):
        import threading
        started = threading.Event()
        monkeypatch.setattr(app_mod, "RAG_WARM_AT_STARTUP", True)
        monkeypatch.setattr(app_mod, "_warm_up", started.set)
        with TestClient(app_mod.app):
            assert started.wait(5), "the lifespan must start the warm-up"

    def test_it_can_be_turned_off(self, monkeypatch):
        called = []
        monkeypatch.setattr(app_mod, "RAG_WARM_AT_STARTUP", False)
        monkeypatch.setattr(app_mod, "_warm_up", lambda: called.append(1))
        with TestClient(app_mod.app):
            pass
        assert called == []

    def test_warm_up_loads_and_searches_once_and_never_raises(self, monkeypatch, caplog):
        import logging
        caplog.set_level(logging.INFO)
        processor = SimpleNamespace(faiss_ds=SimpleNamespace(search_l2=lambda q, k: []))
        monkeypatch.setattr(app_mod, "_get_processor", lambda: processor)
        app_mod._warm_up()
        assert any("warm-up done" in r.getMessage() for r in caplog.records)
        monkeypatch.setattr(app_mod, "_get_processor", lambda: (_ for _ in ()).throw(RuntimeError("no model")))
        app_mod._warm_up()
        assert any("warm-up failed" in r.getMessage() for r in caplog.records)
