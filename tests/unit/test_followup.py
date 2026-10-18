"""SYS-104 (#274), ADR-010: the pure parts of a follow-up's retrieval (newscrawler/web/followup.py).
SYS-143 (#326) refusal/list check, SYS-144 (#327) -nya adverbs, SYS-145 (#328, ADR-014) kept-thread.
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

    @pytest.mark.parametrize("question", [
        "Apa yang sebenarnya terjadi pada Garuda Indonesia?",
        "Bagaimana nasib Sritex selanjutnya?",
        "Apakah harga emas biasanya naik menjelang Lebaran?",
        "Siapa saja tersangka korupsi timah, misalnya?",
        "Apakah Danantara akhirnya membeli saham Garuda?",
        "Seharusnya BI menurunkan suku bunga?",
        "Tampaknya IHSG menguat, kenapa?",
    ])
    def test_an_adverb_ending_in_nya_is_not_a_back_reference(self, question):
        """SYS-144: on the fallback these questions were retrieved with the old thread (0/5)."""
        assert not f.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Apa sebaiknya dilakukan investor?", "Apa sebetulnya masalah utang itu?",
        "Bagaimana nantinya nasib karyawan?", "Sayangnya, apakah IHSG akan turun lagi?",
        "Kapan secepatnya dibeli?", "Apakah subsidi sepenuhnya ditanggung?",
        "Menariknya, apa yang terjadi?", "Pasalnya, siapa yang membayar?",
    ])
    def test_the_wider_adverb_list(self, question):
        """SYS-144 send-back: QA's six held-out adverbs and the corpus-mined sentence adverbs
        (scripts/experiments/sys144/mine_nya_adverbs.py)."""
        assert not f.refers_back(question)

    @pytest.mark.parametrize("question", [
        "Apa yang terjadi sesudahnya?", "Bagaimana setelahnya?", "Apa sebaliknya?",
        "Apakah Sritex akhirnya membayar utangnya?",     # an adverb does not hide a real reference
    ])
    def test_words_that_do_point_back_still_do(self, question):
        assert f.refers_back(question)


class TestRefersToThread:
    """ADR-021 (SYS-144/145 send-back): a follow-up points into its thread only when it holds a
    reference word and names no subject of its own. Pairs from `scripts/experiments/sys144/
    measure_name_gate.py` (production: on-topic cards per path)."""
    FED = ["Apa keputusan The Fed terbaru?"]
    OJK = ["Apa kata OJK soal kredit perbankan?"]
    IHSG = ["Bagaimana kinerja IHSG hari ini?"]

    @pytest.mark.parametrize("previous, question", [
        (FED, "Bagaimana dampaknya ke rupiah?"),
        (["Siapa yang dipanggil KPK pekan ini?"], "Kasusnya tentang apa?"),
        (["Apa kabar program Makan Bergizi Gratis?"], "Siapa pengelolanya?"),
    ])
    def test_a_reference_with_no_name_points_into_the_thread(self, previous, question):
        assert f.refers_to_thread(question, previous)

    @pytest.mark.parametrize("previous, question", [
        (OJK, "Bagaimana nantinya nasib karyawan Sritex?"),          # QA held-out: 1/5 -> 5/5
        (IHSG, "Apa sebetulnya masalah utang Waskita Karya?"),         # 3/5 -> 5/5
        (IHSG, "Berapa utang Waskita Karya dan kapan jatuh temponya?"),  # ADR-014's risk: 1/5 -> 5/5
        (OJK, "Apa itu Danantara dan siapa pemimpinnya?"),
        (["Berapa harga emas Antam hari ini?"], "Siapa CEO Garuda Indonesia dan berapa gajinya?"),
    ])
    def test_a_follow_up_that_names_its_own_subject_is_its_own_question(self, previous, question):
        assert not f.refers_to_thread(question, previous)

    def test_the_rule_does_not_rest_on_the_adverb_list(self):
        """'selambatnya' is on no list: refers_back is fooled, refers_to_thread is not."""
        q = "Kapan selambatnya Danantara membeli saham Garuda?"
        assert f.refers_back(q)
        assert not f.refers_to_thread(q, self.OJK)

    @pytest.mark.parametrize("previous, question", [
        (FED, "Bagaimana dampaknya ke IHSG?"),
        (["Kenapa harga minyak dunia naik?"], "Apa pengaruhnya terhadap Pertamina?"),
        (["Berapa BI-Rate terbaru?"], "Bagaimana dampaknya bagi saham BBRI?"),
        (["Kenapa rupiah melemah pekan ini?"], "Apa imbasnya pada Garuda Indonesia?"),
        (["Apa keputusan OPEC terbaru?"], "Apa dampaknya untuk Pertamina?"),
        (["Kenapa saham GoTo anjlok?"], "Bagaimana reaksinya di Bursa Efek Indonesia?"),
    ])
    def test_a_name_in_an_object_phrase_is_what_the_thread_affects(self, previous, question):
        assert f.refers_to_thread(question, previous)

    @pytest.mark.parametrize("previous, question", [
        (OJK, "Apa yang terjadi pada Sritex dan bagaimana nasib karyawannya?"),
        (["Berapa harga emas Antam hari ini?"], "Bagaimana kabar terbaru di Danantara dan siapa direkturnya?"),
    ])
    def test_a_name_in_an_object_phrase_before_the_reference_is_its_antecedent(self, previous, question):
        """An -nya anaphor points backward: held-out 2/5 -> 5/5 and 0/5 -> 3/5."""
        assert not f.refers_to_thread(question, previous)

    @pytest.mark.parametrize("previous, question", [
        (["Bagaimana kasus korupsi timah?"], "Berapa kerugiannya bagi PT Timah?"),
        (["Bagaimana nasib Sritex?"], "Apakah Sritex akhirnya membayar utangnya?"),
        (FED, "Bagaimana dampaknya pada Oktober 2026?"),           # a month and a year are no subject
        (FED, "Apa kata Menteri soal dampaknya?"),                  # nor is a title
    ])
    def test_only_a_name_the_thread_lacks_is_a_subject_of_its_own(self, previous, question):
        assert f.refers_to_thread(question, previous)

    def test_the_first_reference_decides(self):
        """'dampaknya' has no name before it, so it points into the thread, although the later
        'pergerakannya' finds IHSG before it."""
        q = "Bagaimana dampaknya ke IHSG dan apa kata analis soal pergerakannya?"
        assert f.refers_to_thread(q, self.FED)

    def test_the_accepted_cost(self):
        """ADR-021: a name before the reference that is not its antecedent reads as the follow-up's
        own subject. Retrieved alone: 1/5 avtur cards vs 5/5 with the thread."""
        assert not f.refers_to_thread("Apa kata Garuda soal dampaknya?", ["Kenapa harga avtur naik?"])

    def test_no_reference_is_never_the_thread(self):
        assert not f.refers_to_thread("Bagaimana dengan Pertamina?", ["Kenapa Garuda Indonesia merugi?"])


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

    @pytest.mark.parametrize("reply", [
        "Maaf, saya tidak dapat menulis ulang pertanyaan tersebut.",
        "Mohon maaf, pertanyaan ini tidak jelas.",
        "Saya tidak bisa membantu dengan permintaan ini.",
        "Sebagai AI, saya tidak memiliki akses ke berita.",
        "Pertanyaan: \"Maaf, saya tidak mampu menjawab.\"",       # a label does not hide a refusal
        "Sorry, I cannot rewrite this question.",
        "I can't help with that.",
    ])
    def test_a_refusal_is_not_a_query(self, reply):
        """SYS-143, ADR-010 decision 3: one short line, so only an explicit check stops it."""
        assert f.check(reply) is None

    @pytest.mark.parametrize("reply", ["1. Apa itu Danantara?", "2) Siapa pemimpinnya?",
                                       "- Apa itu Danantara?", "* Apa itu Danantara?", "• Apa itu Danantara?"])
    def test_a_list_item_is_not_a_query(self, reply):
        assert f.check(reply) is None

    @pytest.mark.parametrize("reply", [
        # rewrites logged on production 2026-10-12 (EXPERIMENTS.md, SYS-104)
        "Apa target pertumbuhan kredit perbankan tahun depan menurut OJK?",
        "Berapa harga buyback emas Antam hari ini?",
        "Siapa yang dipanggil KPK pekan ini dan kasusnya tentang apa?",
        "Berapa kerugian negara dalam kasus korupsi tol MBZ?",
        # questions that merely contain the words
        "1.000 pekerja Sritex di-PHK, apa kata Kemnaker?",
        "Apakah BI minta maaf soal rupiah?",
        "-5% IHSG hari ini, kenapa?",
    ])
    def test_real_questions_still_pass(self, reply):
        assert f.check(reply) == reply


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

    def test_a_kept_follow_up_that_refers_back_uses_the_thread(self):
        """SYS-145, ADR-014: the model kept 'Bagaimana dampaknya ke rupiah?' after The Fed (0/5 Fed
        cards alone); '-nya' still points at the Fed decision."""
        fed = ["Apa keputusan The Fed terbaru?"]
        r = f.resolve("Bagaimana dampaknya ke rupiah?", fed, "Bagaimana dampaknya ke rupiah?")
        assert r == f.Retrieval("Bagaimana dampaknya ke rupiah? Apa keputusan The Fed terbaru?",
                                ("Bagaimana dampaknya ke rupiah?", "Apa keputusan The Fed terbaru?"),
                                "Bagaimana dampaknya ke rupiah?", "kept-thread")

    def test_a_kept_topic_switch_with_an_adverb_stays_kept(self):
        """SYS-144 first: an adverb in -nya must not pull a kept switch back to the old thread."""
        q = "Apa yang sebenarnya terjadi pada Garuda Indonesia?"
        assert f.resolve(q, self.PREVIOUS, q) == f.Retrieval(q, (q,), q, "kept")

    def test_the_fallback_for_a_new_subject_is_its_own_words(self):
        assert f.resolve("Apa itu Danantara?", self.PREVIOUS, None) == f.Retrieval(
            "Apa itu Danantara?", ("Apa itu Danantara?",), "Apa itu Danantara?", "fallback-own")

    @pytest.mark.parametrize("q", [
        "Berapa utang Waskita Karya dan kapan jatuh temponya?",   # a real reference, inside: 1/5 -> 5/5
        "Kapan selambatnya Danantara membeli saham Garuda?",       # an adverb on no list
    ])
    @pytest.mark.parametrize("rewritten, how", [("same", "kept"), (None, "fallback-own")])
    def test_a_switch_that_names_its_own_subject_stays_alone_on_both_paths(self, q, rewritten, how):
        """ADR-021 (SYS-144/145 send-back): both questions hold a word `refers_back` flags, and both
        name a subject the thread lacks, so neither is pulled to the OJK thread on either path."""
        assert f.refers_back(q)
        r = f.resolve(q, self.PREVIOUS, q if rewritten == "same" else None)
        assert r == f.Retrieval(q, (q,), q, how)

    @pytest.mark.parametrize("rewritten, how", [("same", "kept-thread"), (None, "fallback-thread")])
    def test_an_object_name_keeps_the_thread_on_both_paths(self, rewritten, how):
        fed = ["Apa keputusan The Fed terbaru?"]
        q = "Bagaimana dampaknya ke IHSG?"
        r = f.resolve(q, fed, q if rewritten == "same" else None)
        assert r.how == how and r.text == "Bagaimana dampaknya ke IHSG? Apa keputusan The Fed terbaru?"


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
