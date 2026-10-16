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

    def test_a_frame_ties_by_word_family(self):
        """Re-run 2026-10-08: this BPIH frame was refused because 'kesepakatan' is not 'menyepakati'."""
        assert st.tied_to_today("Kesepakatan ini mengakhiri pembahasan yang sempat diwarnai usulan komposisi berbeda.",
                                "BPIH 2027 disepakati Rp98,46 juta per jemaah",
                                "Pemerintah dan Komisi VIII DPR menyepakati BPIH 2027 rata-rata Rp98.466.351,35.")
        assert st.tied_to_today("Pelemahan ini berlanjut sejak lama.", "IHSG anjlok", "IHSG terus melemah.")

    @pytest.mark.parametrize("word,stem", [
        ("kesepakatan", "sepakat"), ("disepakati", "sepakat"), ("menyepakati", "sepakat"), ("pelemahan", "lemah"),
        ("melemah", "lemah"), ("memutasi", "mutasi"), ("perombakan", "rombak"), ("berlanjut", "lanjut"),
        ("memukul", "pukul"), ("penurunan", "turun"),
    ])
    def test_stems(self, word, stem):
        assert stem in st.stems(word)

    @pytest.mark.parametrize("word", ["polri", "ihsg", "bank", "kapolda"])
    def test_a_word_is_its_own_family(self, word):
        assert word in st.stems(word) and all(len(s) >= st.MIN_STEM for s in st.stems(word))

    @pytest.mark.parametrize("word", ["diri", "bea", "seni", "kini"])
    def test_no_stem_shorter_than_four_letters(self, word):
        """'di' + 'ri', 'se' + 'ni': a 2-letter stem would tie any two sentences."""
        assert st.stems(word) == {word}

    def test_an_empty_latar_is_tied(self):
        assert st.tied_to_today("", JUDUL, HARI_INI)

    @pytest.mark.parametrize("recap", ["Awal Oktober, Polri memutasi 88 perwira.",
                                       "Pekan lalu, Polri memutasi 88 perwira.",
                                       "Sebelumnya, tiga pekan lalu, Polri memutasi 88 perwira.",
                                       "Sabtu lalu Polri memutasi 88 perwira tinggi."])
    def test_a_recap_opening_on_relative_time_is_not_tied(self, recap):
        """SYS-164 (#359): SYS-159's recap written the way SYS-154 now asks is still a recap."""
        assert not st.tied_to_today(recap, JUDUL, HARI_INI)

    def test_a_since_frame_ties(self):
        assert st.tied_to_today("Sejak awal Oktober, Polri sudah dua kali merombak jabatan Kapolda.", JUDUL, HARI_INI)


class TestTimeAnchors:
    """SYS-164 (#359): a time anchor is a calendar date or a relative time not after "sejak"."""

    def test_dates_and_relative_times_in_order(self):
        assert st.time_anchors("Pekan lalu IHSG turun, Senin (5/10) dan Kamis (8/10) memburuk. Kemarin, kini, "
                               "lalu sejak awal Oktober.") == ["Pekan lalu", "5/10", "8/10", "Kemarin"]

    def test_the_karhutla_latar_of_10_11(self):
        """digests/preview/arcs-v5/2026-10-11: every chosen item told in order. "sejak awal Oktober" is
        the frame, not an anchor; QA counted the latar's 5 with it."""
        latar = ("Gangguan penerbangan di Bandara SMB II Palembang ini berlanjut sejak awal Oktober. Pekan lalu, dua "
                 "pesawat gagal mendarat saat jarak pandang 500 meter, lalu 18 penerbangan tertunda pada Senin (5/10) "
                 "dan 30 penerbangan terdampak pada Kamis (8/10). Kemarin, 15 penerbangan kembali terganggu, dan kini "
                 "OMC yang semula digelar dari Palembang dipindah ke Pangkal Pinang karena asap mengganggu operasi "
                 "modifikasi cuaca.")
        assert st.time_anchors(latar) == ["Pekan lalu", "5/10", "8/10", "Kemarin"]

    @pytest.mark.parametrize("sentence", ["Pada tanggal 3 Oktober, Polri memutasi 88 perwira.",
                                          "Pada hari Sabtu (3/10), Polri memutasi 88 perwira.",
                                          "Pada Sabtu, 3 Oktober, Polri memutasi 88 perwira.",
                                          "Tanggal 3/10, Polri memutasi 88 perwira."])
    def test_more_date_opening_shapes(self, sentence):
        assert st.opens_on_date(sentence) and st.opens_on_time(sentence) and st.date_led(sentence)

    @pytest.mark.parametrize("sentence,opens", [
        ("Awal Oktober, Polri memutasi 88 perwira.", True),
        ("Kemarin Seskab melapor.", True),
        ("Pada pekan lalu Polri memutasi 88 perwira.", True),
        ("Sejak awal Oktober Polri dua kali merombak.", False),
        ("Polri memutasi 88 perwira pekan lalu.", False),
        ("Mutasi ini lanjutan rotasi awal Oktober.", False),
    ])
    def test_opens_on_time(self, sentence, opens):
        assert st.opens_on_time(sentence) is opens
        assert st.time_led(sentence) is opens
        assert not st.opens_on_date(sentence)

    def test_sejak_frames_are_not_anchors(self):
        assert st.time_anchors("Sejak awal Oktober dan sejak pekan lalu harga naik.") == []

    @pytest.mark.parametrize("frame", ["Sejak September, Polri sudah dua kali merombak jabatan Kapolda.",
                                       "Sejak Agustus 2026, Polri sudah dua kali merombak jabatan Kapolda.",
                                       "Polri sudah dua kali merombak jabatan Kapolda sejak September."])
    def test_a_sejak_month_frame_is_not_an_anchor(self, frame):
        """SYS-164 rework (#359): "sejak <bulan>" is a table phrase of its own that *opens* with sejak.
        It was counted as an anchor and an opening, and the tie refused the frame it had accepted."""
        assert st.time_anchors(frame) == []
        assert not st.opens_on_time(frame)
        assert st.tied_to_today(frame, JUDUL, HARI_INI)

    def test_a_sejak_frame_does_not_hide_the_anchors_after_it(self):
        latar = ("Sejak September karhutla meluas. Pekan lalu Seskab melapor, 5/10 rapat digelar, "
                 "dan kemarin asap sampai Malaysia.")
        assert st.time_anchors(latar) == ["Pekan lalu", "5/10", "kemarin"]

    def test_a_calendar_date_after_sejak_is_still_an_anchor(self):
        assert st.time_anchors("Sejak 15/9 gugatan berjalan.") == ["15/9"]

    @pytest.mark.parametrize("sentence,led", [("Polri memutasi 88 perwira pada 3/10.", True),
                                              ("Polri memutasi 88 perwira pekan lalu.", False),
                                              ("Pekan lalu, Polri memutasi 88 perwira.", True)])
    def test_time_led_keeps_a_mid_sentence_pada_date(self, sentence, led):
        """DBT-78 (#362): time_led is date_led (with "pada <date>" anywhere) or a time opening -- the dev's
        Bulog case on #359 ("... pada 25 September")."""
        assert st.time_led(sentence) is led
