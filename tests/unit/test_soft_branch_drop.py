"""SRC-35 (#128): the soft-vertical deny applied once, in the base Crawler,
to every source's branch keys -- word-bounded so `transportasi` is not
`sport`, with per-crawler exceptions for names a 3-title sample proved are
that outlet's business coverage (table on the ticket)."""
from unittest.mock import MagicMock

import pytest

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.infrastructure.datasource.scrapers.crawler import SOFT_BRANCH_WORDS, Crawler


class TestIsSoftBranch:
    @pytest.mark.parametrize("key", [
        "sport", "sports", "olahraga", "bola", "bola-sports", "bali/sport", "jabar/olahraga",
        "sepakbola", "superskor", "sportaliga", "esport", "piala-dunia-2026",
        "showbiz", "seleb", "KlikSeleb", "celebrity", "hiburan", "entertainment", "hype", "korea",
        "musik", "film", "filmon", "idxtainment", "ecotainment", "entertainment_life_style",
        "lifestyle", "gaya-hidup", "fashion", "beauty", "women", "woman", "mom", "cewekbanget",
        "kuliner", "resep", "food", "food-travel", "travel", "wisata",
        "religi", "ramadan", "kalam", "games", "games-news", "quiz", "zodiak", "fiction",
        "fotostop_news", "konsultasigadget", "gadget", "bobo", "intisari", "gridoto", "motorplus",
        "donwori", "advetorial", "siaran-pers", "vstory", "blog", "english", "english_edition",
    ])
    def test_soft_branches_are_dropped(self, key):
        assert Crawler.is_soft_branch(key) is True

    @pytest.mark.parametrize("key", [
        # sampled 2026-09-22 and kept -- the whole point of SRC-35's "verify per
        # source, not per regex": every one of these reads as news or business.
        "transportasi", "teknologi", "tekno", "tekno-sains", "ototekno", "kesehatan", "sehat",
        "otomotif", "edukasi", "syariah", "muslim", "video", "foto", "pariwisata",
        "nasional", "internasional", "ekonomi", "bisnis", "daerah", "megapolitan", "pendidikan",
        "humaniora", "kriminal", "hukum", "politik", "bali/politik", "market-news", "banking",
        "the-founder", "entrepreneur", "mymoney", "research", "news", "berita", "",
    ])
    def test_news_and_business_branches_are_kept(self, key):
        assert Crawler.is_soft_branch(key) is False

    def test_the_transportasi_trap_is_the_reason_matching_is_word_bounded(self):
        assert Crawler.is_soft_branch("sport") and not Crawler.is_soft_branch("transportasi")
        assert Crawler.is_soft_branch("wisata") and not Crawler.is_soft_branch("pariwisata")
        assert Crawler.is_soft_branch("women") and not Crawler.is_soft_branch("womenomics")

    def test_every_vocabulary_word_is_lowercase_and_matches_itself(self):
        for word in SOFT_BRANCH_WORDS:
            assert word == word.lower(), word
            assert Crawler.is_soft_branch(word), word


class TestPerCrawlerExceptions:
    def test_wartaekonomi_keeps_travel_and_kontan_keeps_english(self):
        # Their samples are cited in each crawler; every other source drops both.
        assert CRAWLER_DICT["WARTAEKONOMI"].is_soft_branch("travel") is False
        assert CRAWLER_DICT["KONTAN"].is_soft_branch("english") is False
        assert CRAWLER_DICT["JPNN"].is_soft_branch("english") is True
        assert CRAWLER_DICT["JPNN"].is_soft_branch("travel") is True
        assert CRAWLER_DICT["WARTAEKONOMI"].is_soft_branch("english_edition") is True

    def test_an_exception_does_not_leak_to_other_crawlers(self):
        assert Crawler.is_soft_branch("travel") is True and Crawler.is_soft_branch("english") is True


class TestDropSoftBranches:
    def _crawler(self):
        c = Crawler()
        c.website_name = "TEST"
        return c

    def test_drops_the_soft_keys_keeps_the_rest_and_logs_once(self, caplog):
        import logging
        c = self._crawler()
        branches = {"nasional": "n", "bola": "b", "ekonomi": "e", "gaya-hidup": "g", "transportasi": "t"}
        with caplog.at_level(logging.INFO, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            kept = c.drop_soft_branches(branches)
        assert kept == {"nasional": "n", "ekonomi": "e", "transportasi": "t"}
        lines = [r.message for r in caplog.records if "soft branch(es)" in r.message]
        assert len(lines) == 1 and "bola" in lines[0] and "gaya-hidup" in lines[0] and "2 soft" in lines[0]

    def test_nothing_to_drop_logs_nothing(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            kept = self._crawler().drop_soft_branches({"nasional": "n"})
        assert kept == {"nasional": "n"}
        assert not [r for r in caplog.records if "soft branch(es)" in r.message]

    def test_empty_and_none(self):
        c = self._crawler()
        assert c.drop_soft_branches({}) == {} and c.drop_soft_branches(None) == {}

    def test_get_news_in_bulk_never_scrapes_a_soft_branch(self):
        c = self._crawler()
        c.page_loader = MagicMock()
        c.page_loader.get_soup.return_value = MagicMock()
        c._get_branches = MagicMock(return_value={"ekonomi": "e-link", "bola": "b-link"})
        c._scrape = MagicMock(return_value=[{"link": "x"}])
        assert c.get_news_in_bulk() == [{"link": "x"}]
        assert c._scrape.call_count == 1
        assert c._scrape.call_args.kwargs["branch_name"] == "ekonomi"
