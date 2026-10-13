"""SYS-156/159/160 (#351/#354/#355): what makes a story arc's back-story read as a
chronicle, measured once for both the parse refusal and the replay's metrics.
The strings are the 2026-10-11 Polri mutasi arc the owner read, and the research
file's rewrite of it (.10x/reviews/2026-10-14-arc-writing-research.md)."""
import pytest

from newscrawler.core import arc_style as st

JUDUL = "Polri Mutasi 199 Perwira, Kakorlantas dan Tiga Kapolda Berganti"
HARI_INI = ("Polri memutasi 199 perwira tinggi dan perwira menengah, termasuk Kakorlantas dan tiga Kapolda. "
            "Kadiv Humas Polri Irjen Johnny Eddizon Isir mengonfirmasi mutasi itu.")
BEFORE = ("Mutasi ini melanjutkan perombakan yang berjalan sejak awal Oktober. Pada 3/10, Polri memutasi 88 perwira "
          "tinggi dan menengah termasuk 19 jabatan Kapolda. Pada 5/10, peta mutasi 88 perwira itu dibahas, dan pada "
          "7/10 disebut Kapolda Metro Jaya kini dijabat Dadang Hartanto. Pada 9/10, Kapolri Suyudi Ario Seto memimpin "
          "sertijab.")
AFTER = ("Ini gelombang kedua perombakan Polri bulan ini. Gelombang pertama di awal Oktober memindahkan 88 perwira "
         "dan mengganti 19 Kapolda, termasuk Kapolda Metro Jaya yang kini dijabat Komjen Dadang Hartanto. Kali ini "
         "giliran Korlantas dan tiga Polda lain.")


class TestDateLed:
    @pytest.mark.parametrize("sentence", [
        "Pada 3/10, Polri memutasi 88 perwira.",
        "pada Rabu (24/9) rapat digelar.",
        "24/9: IHSG ditutup melemah.",
        "Sebelumnya, pada 19/9, banjir menerjang Pasaman.",
        "Sejak 15/9 gugatan berjalan.",
        "Gugatan berjalan sejak lama, dan pada 24 September hakim menunda sidang.",     # carries "pada <date>"
    ])
    def test_date_led(self, sentence):
        assert st.date_led(sentence)

    @pytest.mark.parametrize("sentence", [
        "Ini gelombang kedua perombakan Polri bulan ini.",
        "Level 6.000 sudah goyah sejak awal bulan.",
        "Surat telegram tertanggal 10 Oktober 2026 itu diteken Kapolri.",                # a date, not a "pada <date>"
        "Kebijakan ini berlaku 1/11.",
    ])
    def test_not_date_led(self, sentence):
        assert not st.date_led(sentence)

    @pytest.mark.parametrize("sentence,opens", [
        ("Sebelumnya, pada 19/9, banjir menerjang Pasaman.", True),
        ("Sementara itu 24/9 rupiah melemah.", True),
        ("Gugatan berjalan sejak lama, dan pada 24 September hakim menunda sidang.", False),
        ("Tidak ada tanggal di sini.", False),
    ])
    def test_opens_on_date(self, sentence, opens):
        """What SYS-159 refuses as a first sentence: opening on the date, after at most a connector."""
        assert st.opens_on_date(sentence) is opens

    def test_the_owners_example_is_a_chronicle_and_the_rewrite_is_not(self):
        assert [st.date_led(s) for s in st.sentences(BEFORE)] == [False, True, True, True]
        assert not any(st.date_led(s) for s in st.sentences(AFTER))


class TestOpenings:
    def test_two_sentences_on_the_same_word(self):
        assert st.repeated_opening(BEFORE) == "pada"

    def test_distinct_openings(self):
        assert st.repeated_opening(AFTER) is None and st.repeated_opening("") is None

    def test_case_does_not_matter(self):
        assert st.repeated_opening("Harga naik. harga turun lagi.") == "harga"


class TestNonEvents:
    def test_process_verbs(self):
        assert st.non_events(BEFORE) == ["dibahas", "disebut"]
        assert st.non_events(AFTER) == []


class TestTiedToToday:
    def test_the_rewrite_ties_by_a_name(self):
        """'perombakan' is not today's 'memutasi': the frame ties by 'Polri'. An event-word-only rule
        (SYS-159 as filed) refused the research file's own example."""
        assert st.tied_to_today(AFTER, JUDUL, HARI_INI)

    def test_a_free_standing_recap_is_not_tied(self):
        """SYS-159's example: opening on a past date, however many words it shares with today."""
        assert not st.tied_to_today("Pada 3/10, Polri memutasi 88 perwira tinggi.", JUDUL, HARI_INI)

    def test_a_frame_that_shares_no_word_with_today_is_not_tied(self):
        """Replay 2026-10-12: a frame about 'pelemahan', when today's IHSG text says 'anjlok'."""
        assert not st.tied_to_today("Pelemahan ini berlanjut sejak lama.", "IHSG anjlok 2,59%",
                                    "IHSG ditutup anjlok 2,59% ke level 5.936,15.")

    def test_an_empty_latar_is_tied(self):
        assert st.tied_to_today("", JUDUL, HARI_INI)
