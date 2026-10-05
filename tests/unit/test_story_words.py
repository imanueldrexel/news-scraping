"""SYS-86 (#246), SYS-80 (#236): which words of a story's text say what it is about,
and which of them are names. The echo guard and the subject check both read them."""
import pytest

from newscrawler.core import story_words as sw


class TestContentWords:
    @pytest.mark.parametrize("text,word", [
        ("Kata Presiden Prabowo Subianto.", "presiden"),          # a title names a post, not who holds it
        ("Lapor ke Gubernur Jawa Barat.", "gubernur"),
        ("Rapat pada Oktober 2026.", "oktober"),                    # a month is a date
        ("Program Oktober-Desember 2026.", "oktober-desember"),
        ("Nilai proyek senilai Rp3,5 triliun.", "triliun"),          # a number's unit
        ("Nilai proyek senilai Rp3,5 triliun.", "senilai"),
        ("Harga Rp2.574.000 per gram.", "rp2"),                     # a token with a digit
        ("Harga minyak US$84 per barel.", "us"),                    # a currency prefix
        ("Rapat yang digelar di Jakarta.", "yang"),
        # replay 2026-10-05: names the SYS-80 subject check was held to, none of them a subject
        ("Kebijakan The Fed menekan emas.", "the"),
        ("Kejagung tetapkan PT CNI tersangka.", "pt"),
        ("Saham PACK Tbk naik.", "tbk"),
        ("Kasus Influenza A naik.", "a"),
        ("Pemerintah umumkan Paket IV.", "iv"),
        ("Rapat Komisi VIII DPR.", "viii"),
    ])
    def test_not_a_content_word(self, text, word):
        assert word not in sw.content_words(text)

    def test_names(self):
        words = sw.content_words("Pemerintah salurkan BSU. Kata Menkeu Purbaya, dana siap.")
        assert words["bsu"] is True and words["purbaya"] is True and words["menkeu"] is True
        assert words["pemerintah"] is False and words["dana"] is False
        assert sw.names("Saham terafiliasi Haji Isam naik 133,88% YTD.") == {"haji", "isam", "ytd"}

    def test_roman_numerals_only_when_they_are_one(self):
        words = sw.content_words("Saham XL dan VIX turun, kata DPR.")
        assert {"xl", "vix", "dpr"} <= set(words)

    def test_a_hyphenated_name_also_gives_its_parts(self):
        assert sw.names("Gencatan senjata AS-Iran berlaku.") >= {"as-iran", "as", "iran"}

    def test_a_word_is_a_name_when_it_is_one_anywhere_in_the_text(self):
        assert sw.content_words("Iran menolak. Trump menolak proposal Iran.")["iran"] is True


class TestVocabulary:
    def test_every_word_lower_cased_and_the_parts_of_a_hyphenated_one(self):
        assert sw.vocabulary("BI menahan BI-Rate, kata Bank Indonesia.") >= {"bi", "bi-rate", "rate", "bank", "kata"}
