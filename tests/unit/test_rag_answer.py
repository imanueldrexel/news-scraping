"""SYS-99 (#268) / SYS-93 (#262): the search answer as data -- the prompt, Markdown
cleanup, citation parsing (only cards that exist become links) and the number check."""
from datetime import date

import pytest

from newscrawler.core import web_copy as copy
from newscrawler.web import answer as a

TODAY = date(2026, 10, 7)   # a Wednesday


def _hit(source="KONTAN", day=date(2026, 10, 5), title="Rupiah Melemah ke Rp16.420",
         text="Rupiah ditutup melemah 0,4% ke Rp16.420 per dolar AS pada Senin.", lead=""):
    return {"source": source, "posted_date": day, "title": title, "text_content": text, "l1_text": lead}


def _texts(segments):
    return [(s.kind, s.text, s.n) for s in segments]


class TestPrompt:
    def test_states_today_in_indonesian_and_numbers_the_articles(self):
        prompt = a.build_prompt("Kenapa rupiah melemah?", [_hit(), _hit("CNBC", title="Asing Jual")], [], TODAY)
        assert "Hari ini Rabu, 7 Oktober 2026." in prompt
        assert "[1] Kontan · Senin, 5 Okt 2026 · Rupiah Melemah ke Rp16.420" in prompt
        assert "[2] CNBC Indonesia · Senin, 5 Okt 2026 · Asing Jual" in prompt
        assert prompt.rstrip().endswith("Pertanyaan: Kenapa rupiah melemah?")

    def test_carries_the_fixed_not_enough_sentence_and_the_rules(self):
        prompt = a.build_prompt("q", [_hit()], [], TODAY)
        assert f'tulis persis: "{copy.NOT_ENOUGH}"' in prompt
        assert "Total maks. 120 kata" in prompt
        assert "tanpa Markdown" in prompt

    def test_no_internal_source_name_or_raw_date_in_the_articles(self):
        prompt = a.build_prompt("q", [_hit()], [], TODAY)
        assert "KONTAN" not in prompt and "20261005" not in prompt and "Oct" not in prompt

    def test_history_is_stripped_of_old_citations_and_limited(self):
        history = [{"question": f"q{i}", "answer": f"jawaban {i} [1][2]"} for i in range(5)]
        text = a.history_text(history)
        assert "[1]" not in text and "q0" not in text and "q4" in text
        assert text.count("T: ") == a.HISTORY_TURNS

    def test_no_history_says_so(self):
        assert "Riwayat:\nTidak ada." in a.build_prompt("q", [_hit()], [], TODAY)

    def test_excerpt_puts_the_lead_before_the_matched_paragraph_once(self):
        hit = _hit(text="Paragraf yang cocok dengan pertanyaan.", lead="Pembuka artikel: siapa, apa, kapan.")
        assert a.excerpt(hit) == "Pembuka artikel: siapa, apa, kapan. … Paragraf yang cocok dengan pertanyaan."
        same = _hit(text="Pembuka artikel sama.", lead="Pembuka artikel sama.")
        assert a.excerpt(same) == "Pembuka artikel sama."


class TestClean:
    @pytest.mark.parametrize("raw, expected", [
        ("**Rupiah** melemah", "Rupiah melemah"),
        ("__Rupiah__ melemah", "Rupiah melemah"),
        ("## Ringkasan\nRupiah melemah", "Ringkasan\nRupiah melemah"),
        ("* satu\n* dua", "- satu\n- dua"),
        ("1. satu\n2) dua", "- satu\n- dua"),
        ("• satu", "- satu"),
        ("ini *penting* sekali", "ini penting sekali"),
        ("kode `x`", "kode x"),
        ("a\n\n\n\nb", "a\n\nb"),
    ])
    def test_markdown_never_reaches_the_reader_as_symbols(self, raw, expected):
        assert a.clean(raw) == expected

    def test_citations_and_arithmetic_stars_survive(self):
        assert a.clean("naik 2 * 3 kali [1][2]") == "naik 2 * 3 kali [1][2]"


class TestParse:
    def test_a_citation_in_range_is_a_citation_segment(self):
        segs = a.segments("Rupiah melemah [2].", 3)
        assert _texts(segs) == [("text", "Rupiah melemah ", 0), ("cite", "[2]", 2), ("text", ".", 0)]

    def test_an_out_of_range_citation_stays_plain_text(self):
        assert _texts(a.segments("lihat [9]", 3)) == [("text", "lihat [9]", 0)]
        assert _texts(a.segments("lihat [0]", 3)) == [("text", "lihat [0]", 0)]

    def test_a_bracket_with_any_number_out_of_range_stays_whole(self):
        assert _texts(a.segments("lihat [2, 9]", 3)) == [("text", "lihat [2, 9]", 0)]

    @pytest.mark.parametrize("written, numbers", [("[1][3]", [1, 3]), ("[1, 3]", [1, 3]), ("[1-3]", [1, 2, 3]),
                                                  ("[1–3]", [1, 2, 3]), ("[2; 4]", [2, 4])])
    def test_several_citations(self, written, numbers):
        assert [s.n for s in a.segments(f"fakta {written}", 5) if s.kind == "cite"] == numbers

    def test_a_long_range_is_not_a_citation(self):
        assert all(s.kind == "text" for s in a.segments("tahun [1-40]", 50))

    def test_words_in_brackets_are_text(self):
        assert _texts(a.segments("[KONTAN, 05 Oct 2026]", 3)) == [("text", "[KONTAN, 05 Oct 2026]", 0)]

    def test_paragraphs_and_bullets(self):
        blocks = a.parse("Jawaban langsung [1].\n- poin satu [2]\n- poin dua\n\nPenutup.", 2)
        assert [b.kind for b in blocks] == ["p", "ul", "p"]
        assert len(blocks[1].items) == 2
        assert a.cited(blocks) == [1, 2]

    def test_a_wrapped_paragraph_is_one_paragraph(self):
        blocks = a.parse("baris satu\nbaris dua", 1)
        assert len(blocks) == 1 and blocks[0].items[0][0].text == "baris satu baris dua"


class TestNumberCheck:
    def test_a_number_from_the_cited_article_passes(self):
        hits = [_hit()]
        assert a.unverified_number("Rupiah ditutup di Rp16.420 [1].", hits, [1], TODAY) is None

    def test_a_number_no_article_has_is_reported(self):
        assert a.unverified_number("Rupiah ditutup di Rp16.500 [1].", [_hit()], [1], TODAY) == "16.500"

    def test_citation_numbers_are_not_checked_as_numbers(self):
        assert a.unverified_number("Rupiah melemah [1][3].", [_hit(), _hit(), _hit()], [1, 3], TODAY) is None

    def test_only_the_cited_articles_count(self):
        hits = [_hit(text="tanpa angka"), _hit(text="naik 7,5 persen")]
        assert a.unverified_number("naik 7,5 persen [1]", hits, [1], TODAY) == "7,5"
        assert a.unverified_number("naik 7,5 persen [2]", hits, [2], TODAY) is None

    def test_uncited_answer_is_held_to_all_articles(self):
        hits = [_hit(text="tanpa angka"), _hit(text="naik 7,5 persen")]
        assert a.unverified_number("naik 7,5 persen", hits, [], TODAY) is None

    def test_the_articles_dates_and_today_are_sources(self):
        # "Senin, 5 Oktober" comes from the card header; "7 Oktober 2026" is today, stated in the prompt
        assert a.unverified_number("Pada Senin, 5 Oktober, hingga hari ini 7 Oktober 2026 [1].",
                                   [_hit()], [1], TODAY) is None

    def test_a_decimal_shift_is_a_different_number(self):
        assert a.unverified_number("melemah 4% [1]", [_hit()], [1], TODAY) == "4"
