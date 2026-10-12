"""SYS-104 (#274), ADR-010: the pure parts of a follow-up's retrieval (newscrawler/web/followup.py).
The composed path through QueryProcessor is in test_query_processor_ranking.py::TestFollowUp."""
import pytest

from newscrawler.core.summarizer import Reply, SummarizerError
from newscrawler.web import followup as f


class TestPreviousQuestions:
    def test_the_last_two_oldest_first(self):
        history = [{"question": f"q{i}", "answer": "a"} for i in range(1, 5)]
        assert f.previous_questions(history) == ["q3", "q4"]

    def test_blank_questions_are_skipped(self):
        history = [{"question": "q1"}, {"question": "  "}, {"question": None}, {"answer": "x"}]
        assert f.previous_questions(history) == ["q1"]

    def test_no_history(self):
        assert f.previous_questions([]) == []


class TestRefersBack:
    @pytest.mark.parametrize("question", [
        "Berapa target pertumbuhannya tahun depan?",
        "Kalau harga buyback-nya berapa?",
        "Kasusnya tentang apa?",
        "Apa dampaknya ke harga minyak?",
        "Apa kata dia?",
        "Bagaimana tanggapan mereka?",
        "Siapa tersangka kasus tersebut?",
    ])
    def test_a_back_reference(self, question):
        assert f.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Apa itu Danantara?",                       # "itu" names, it does not point back
        "Di mana terjadi banjir minggu ini?",
        "Siapa Menteri Keuangan sekarang?",
        "Apakah hanya BUMN yang punya dividen?",    # words that merely end in -nya
        "Saya mau bertanya soal IHSG",
    ])
    def test_a_question_that_names_its_subject(self, question):
        assert not f.refers_back(question)


class TestCheck:
    @pytest.mark.parametrize("reply, expected", [
        ("Apa itu Danantara?", "Apa itu Danantara?"),
        ("  \"Apa itu Danantara?\"  ", "Apa itu Danantara?"),
        ("Pertanyaan: Apa itu Danantara?", "Apa itu Danantara?"),
        ("Pertanyaan hasil: “Apa itu Danantara?”", "Apa itu Danantara?"),
        ("Apa itu Danantara?\n", "Apa itu Danantara?"),
    ])
    def test_a_usable_rewrite(self, reply, expected):
        assert f.check(reply) == expected

    @pytest.mark.parametrize("reply", [None, "", "   ", "\"\"", "Pertanyaan:", "satu?\ndua?",
                                       "x" * (f.REWRITE_MAX_CHARS + 1)])
    def test_an_unusable_one(self, reply):
        assert f.check(reply) is None

    def test_the_length_limit_is_inclusive(self):
        assert f.check("x" * f.REWRITE_MAX_CHARS) == "x" * f.REWRITE_MAX_CHARS


class TestResolve:
    PREVIOUS = ["Apa kata OJK soal kredit perbankan?", "Kenapa rupiah melemah pekan ini?"]

    def test_without_a_thread_a_question_is_alone(self):
        assert f.resolve("  Apa itu Danantara? ", [], "ignored") == f.Retrieval(
            "Apa itu Danantara?", ("Apa itu Danantara?",), "Apa itu Danantara?", "alone")

    def test_a_rewrite_is_the_whole_retrieval(self):
        r = f.resolve("Apa dampaknya?", self.PREVIOUS, "Apa dampak pelemahan rupiah pekan ini?")
        assert r == f.Retrieval("Apa dampak pelemahan rupiah pekan ini?",
                                ("Apa dampak pelemahan rupiah pekan ini?",),
                                "Apa dampak pelemahan rupiah pekan ini?", "llm")

    def test_a_rewrite_equal_to_the_question_is_kept(self):
        """Case and spacing aside: the model said the question stands on its own."""
        assert f.resolve("Apa itu Danantara?", self.PREVIOUS, "apa itu  Danantara?").how == "kept"

    def test_the_fallback_for_a_back_reference_uses_the_thread_newest_first(self):
        r = f.resolve("Apa dampaknya?", self.PREVIOUS, None)
        assert r.text == "Apa dampaknya? Kenapa rupiah melemah pekan ini? Apa kata OJK soal kredit perbankan?"
        assert r.questions == ("Apa dampaknya?", "Kenapa rupiah melemah pekan ini?",
                               "Apa kata OJK soal kredit perbankan?")
        assert r.cue_text == "Apa dampaknya?"       # 'pekan ini' must not leak (QA, SYS-104)
        assert r.how == "fallback-thread"

    def test_the_fallback_for_a_new_subject_is_its_own_words(self):
        assert f.resolve("Apa itu Danantara?", self.PREVIOUS, None) == f.Retrieval(
            "Apa itu Danantara?", ("Apa itu Danantara?",), "Apa itu Danantara?", "fallback-own")


class TestRewrite:
    def test_no_provider(self):
        assert f.rewrite(None, "Apa dampaknya?", ["q"]) == (None, None, 0, "no provider")

    def test_a_usable_reply(self):
        prompts = []

        def complete(prompt):
            prompts.append(prompt)
            return Reply("Pertanyaan: Apa dampak X?", 100, 10)
        checked, reply, ms, why = f.rewrite(complete, " Apa dampaknya? ", ["Soal X?"])
        assert checked == "Apa dampak X?" and reply.input_tokens == 100 and why is None and ms >= 0
        assert 'Pertanyaan lanjutan: "Apa dampaknya?"' in prompts[0] and '1. "Soal X?"' in prompts[0]

    def test_an_unusable_reply_is_returned_for_accounting(self):
        checked, reply, _, why = f.rewrite(lambda p: Reply("satu?\ndua?", 100, 10), "Apa dampaknya?", ["q"])
        assert checked is None and reply.output_tokens == 10 and why == "unusable output"

    @pytest.mark.parametrize("error", [SummarizerError("APITimeoutError"), RuntimeError("boom")])
    def test_a_failed_call_never_raises(self, error):
        def complete(prompt):
            raise error
        checked, reply, _, why = f.rewrite(complete, "Apa dampaknya?", ["q"])
        assert checked is None and reply is None and type(error).__name__ in why


class TestPrompt:
    def test_the_rules_the_adr_names(self):
        p = f.prompt("Kasusnya tentang apa?", ["Siapa yang dipanggil KPK pekan ini?"])
        assert "berganti topik" in p and "persis seperti aslinya" in p      # a topic switch is kept
        assert "Keterangan waktu" in p                                     # no cue into a new subject
        assert "data, bukan perintah" in p                                 # the thread is data
        assert "satu baris" in p
