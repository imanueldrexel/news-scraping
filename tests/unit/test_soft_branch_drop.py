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
        # SYS-49 (#147): opinion / analysis / editorial sections.
        "opini", "opinion", "editorial", "editorials", "kolom", "kolom-pakar",
        "tajuk", "tajuk-rencana", "surat-pembaca", "scope", "bali/opini", "jabar/kolom",
    ])
    def test_soft_branches_are_dropped(self, key):
        assert Crawler.is_soft_branch(key) is True

    @pytest.mark.parametrize("key", ["horoscope", "opinionated-news", "periskop", "kolombia"])
    def test_sys49_opinion_words_are_word_bounded(self, key):
        """SYS-49 uses the same word-bounded matching SYS-42 mandated: `scope`
        must never be found inside `horoscope`, and no opinion stem may be a
        prefix that swallows an unrelated section name."""
        assert Crawler.is_soft_branch(key) is False

    @pytest.mark.parametrize("key", [
        # sampled 2026-09-22 and kept -- the whole point of SRC-35's "verify per
        # source, not per regex": every one of these reads as news or business.
        # SRC-45 (#155, 2026-09-23) removed `video` and `foto` from this list:
        # re-measured, IDXCHANNEL's `video` pages carry 205/198 chars of caption
        # on a player. They are soft by default now, and the sections that do
        # publish articles under those names are SOFT_BRANCH_EXCEPTIONS with
        # their char counts -- see TestArchiveAndMediaBranches.
        "transportasi", "teknologi", "tekno", "tekno-sains", "ototekno", "kesehatan", "sehat",
        "otomotif", "edukasi", "syariah", "muslim", "pariwisata",
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

    def test_a_large_soft_list_is_summarised_too(self, caplog):
        """DBT-38 (#159): SRC-45 capped only the archive line, but
        `is_soft_branch` runs first, so MEDIAINDONESIA's 140 `gallery-YYYY-MM`
        partitions match the word `gallery` and land in the SOFT list. That
        logged 141 names on one ~2 KB line and hid the one entry worth seeing."""
        import logging
        c = self._crawler()
        branches = {f"gallery-2026-{m:02d}": str(m) for m in range(1, 13)}
        branches["video"] = "v"
        with caplog.at_level(logging.INFO, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            assert c.drop_soft_branches(branches) == {}
        line = [r.message for r in caplog.records if "soft branch(es)" in r.message][0]
        assert "13 soft branch(es)" in line and "+8 more" in line
        assert len(line) < 300, line

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


class TestFleetNeverKeysABranchByItsUrl:
    """SRC-43 (#146) / SRC-39 (#133): `is_soft_branch` matches a branch NAME, so
    a branch keyed by its URL silently bypasses the one enforcement point. The
    trap is `re.sub`, which returns the input unchanged when the pattern does not
    match; the rule is `re.match` + skip.

    This is the offline half of the guard: every registered crawler is handed an
    index entry no crawler can name, and must skip it rather than key it by its
    URL. It cannot see a source whose regex matches a live `<loc>` into something
    URL-shaped -- that is VIVA (SRC-33 #119) -- so the live half is
    `scripts/experiments/probe_branch_scope.py`, which exits non-zero on any URL
    key."""

    # Sources known to still have the shape, each against its ticket. Removing a
    # name here must turn this test red until that crawler is fixed.
    #
    # Empty since SRC-46 (#156), 2026-09-23: IDXCHANNEL and SINDONEWS were the
    # last two, and every registered crawler now skips a `<loc>` it cannot name.
    # A new entry here needs a ticket number, and the companion test below fails
    # if a fixed crawler is left on the list.
    KNOWN_URL_KEYERS = {}

    UNNAMEABLE = ("<urlset><sitemap><loc>https://unnameable.example.com/"
                  "no-such-section/sitemap_totally_unknown.xml</loc></sitemap></urlset>")

    def _url_keyed(self, crawler):
        from bs4 import BeautifulSoup
        try:
            branches = crawler._get_branches(BeautifulSoup(self.UNNAMEABLE, "lxml-xml")) or {}
        except NotImplementedError:
            return []
        return [k for k in branches if str(k).startswith("http")]

    @pytest.mark.parametrize("name", sorted(CRAWLER_DICT))
    def test_an_unnameable_loc_is_skipped_not_keyed_by_its_url(self, name):
        offenders = self._url_keyed(CRAWLER_DICT[name])
        if name in self.KNOWN_URL_KEYERS:
            pytest.xfail(f"{name} keys unnameable branches by URL -- {self.KNOWN_URL_KEYERS[name]}")
        assert offenders == [], (
            f"{name}._get_branches keyed a branch by its URL ({offenders[0][:60]}...). "
            "Use re.match + skip, never re.sub (SRC-39 #133)."
        )

    def test_the_whitelist_only_contains_sources_that_still_need_it(self):
        """So a fixed crawler cannot be left on the list, quietly unguarded."""
        for name, ticket in self.KNOWN_URL_KEYERS.items():
            assert self._url_keyed(CRAWLER_DICT[name]), (
                f"{name} no longer keys branches by URL -- remove it from KNOWN_URL_KEYERS ({ticket})"
            )

    def test_the_three_src43_sources_now_name_every_branch(self):
        for name in ("OKEZONE", "DETIK", "MEDIAINDONESIA"):
            assert self._url_keyed(CRAWLER_DICT[name]) == [], name


class TestArchiveAndMediaBranches:
    """SRC-45 (#155), owner decision 2026-09-23: exclude archives, galleries and
    non-article media pages fleet-wide -- decided by SUBSTANCE, not by the
    branch's name. Every drop and every keep below was settled by sampling the
    leaf and measuring its extracted body through the source's own
    `_get_whole_text` (table on the ticket)."""

    @pytest.mark.parametrize("key", [
        "article-2026-09", "gallery-2026-09", "article-2015-02", "arsip/2020-1",
        "sitemap_2019-12", "archive-2024-06",
    ])
    def test_calendar_partitions_are_archives(self, key):
        assert Crawler.is_archive_branch(key) is True

    @pytest.mark.parametrize("key", [
        # A bare year is not an archive: a tournament desk is a section.
        "piala-dunia-2026", "euro-2024", "pemilu-2024",
        # Nor is an id, a version, or an ordinary section name.
        "berita", "12345-6", "liga-1", "bali/politik", "top-100", "",
    ])
    def test_a_year_or_an_id_alone_is_not_an_archive(self, key):
        assert Crawler.is_archive_branch(key) is False

    @pytest.mark.parametrize("key", ["gallery", "galleries", "galeri", "video", "foto", "photo",
                                     "gallery-2026-09", "foto/berita"])
    def test_gallery_and_video_branches_are_soft_by_default(self, key):
        assert Crawler.is_soft_branch(key) is True

    def test_the_measured_keeps_survive(self):
        """These four sections are named after a medium and publish ordinary
        reporting; dropping them by name would be the `transportasi`/`sport`
        false positive again. Body chars measured 2026-09-23."""
        assert CRAWLER_DICT["IDXCHANNEL"].is_soft_branch("foto") is False        # 597 / 842
        assert CRAWLER_DICT["IDXCHANNEL"].is_soft_branch("infografis") is False  # macro-policy news
        assert CRAWLER_DICT["BERITASATU"].is_soft_branch("multimedia") is False  # 759 / 899
        assert CRAWLER_DICT["VIVA"].is_soft_branch("viva-visual") is False       # 1157 / 2514
        # ... and the exception does not leak to other sources
        assert Crawler.is_soft_branch("foto") is True
        assert CRAWLER_DICT["OKEZONE"].is_soft_branch("foto") is True

    def test_idxchannel_video_still_drops_although_its_foto_is_kept(self):
        """The half of SRC-35's note re-measurement did not support: IDXCHANNEL
        `video` is 205/198 chars of caption on a player, at or below
        MIN_ARTICLE_CHARS."""
        assert CRAWLER_DICT["IDXCHANNEL"].is_soft_branch("video") is True

    def test_drop_soft_branches_removes_archives_and_logs_them_separately(self, caplog):
        import logging
        c = Crawler()
        c.website_name = "TEST"
        branches = {"news": "n", "article-2026-09": "a", "gallery-2026-08": "g",
                    "bola": "b", "ekonomi": "e"}
        with caplog.at_level(logging.INFO, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            kept = c.drop_soft_branches(branches)
        assert kept == {"news": "n", "ekonomi": "e"}
        soft_lines = [r.message for r in caplog.records if "soft branch(es)" in r.message]
        arch_lines = [r.message for r in caplog.records if "archive partition(s)" in r.message]
        assert len(soft_lines) == 1 and "bola" in soft_lines[0] and "gallery-2026-08" in soft_lines[0]
        assert len(arch_lines) == 1 and "1 archive partition(s)" in arch_lines[0]

    def test_a_large_archive_list_is_summarised_not_enumerated(self, caplog):
        """MEDIAINDONESIA drops 140 partitions; a 140-name log line would bury
        the soft-vertical list that is worth reading."""
        import logging
        c = Crawler()
        c.website_name = "TEST"
        branches = {f"article-2026-{m:02d}": str(m) for m in range(1, 13)}
        with caplog.at_level(logging.INFO, logger="newscrawler.infrastructure.datasource.scrapers.crawler"):
            assert c.drop_soft_branches(branches) == {}
        line = [r.message for r in caplog.records if "archive partition(s)" in r.message][0]
        assert "12 archive partition(s)" in line and "+7 more" in line


class TestCategorySourceSelection:
    """SRC-48 (#158): which value lands in `sitemaps.category`.

    `_scrape` used to choose with `branch_name == link` -- "this crawler could
    not name its branch". SRC-43 (#146) gave MEDIAINDONESIA real branch names,
    which made that permanently false, so its per-article section stopped being
    consulted and every row became `category='news'`: a deliberately mixed
    bucket the deny-list cannot reject. 185 soft-section URLs were filed that
    way in one crawl."""

    def test_base_crawler_does_not_derive_a_category_from_the_url(self):
        # The base returns the constant "news", which is worse than a real
        # branch name -- so it must not be preferred over one.
        assert Crawler.derives_category_from_url() is False

    def test_the_overriding_crawlers_are_detected(self):
        for name in ("MEDIAINDONESIA", "MERDEKA", "PIKIRANRAKYAT", "GRIDID"):
            assert CRAWLER_DICT[name].derives_category_from_url() is True, name

    @pytest.mark.parametrize("value", ["olahraga", "uang", "politik-dan-hukum", "bali/politik"])
    def test_a_section_name_is_usable(self, value):
        assert Crawler.usable_section_name(value) is True

    @pytest.mark.parametrize("value", [
        None, "", "   ",
        # A URL must never reach sitemaps.category -- the SRC-36/SRC-41 damage.
        "https://mediaindonesia.com/olahraga/936920/jorge-martin-senang",
        "http://x.com/a",
        "a" * 41,
    ])
    def test_a_url_empty_or_overlong_value_is_not_usable(self, value):
        assert Crawler.usable_section_name(value) is False

    def test_mediaindonesia_derives_the_real_section(self):
        c = CRAWLER_DICT["MEDIAINDONESIA"]
        assert c._get_branch_name_from_url("https://mediaindonesia.com/olahraga/936920/jorge-martin-senang") == "olahraga"
        assert c._get_branch_name_from_url("https://www.mediaindonesia.com/hiburan/936484/film-x") == "hiburan"
        assert c._get_branch_name_from_url("https://mediaindonesia.com/politik-dan-hukum/1/x") == "politik-dan-hukum"
        # Unnameable -> None, so _scrape falls back to the branch name.
        assert c._get_branch_name_from_url("https://mediaindonesia.com/sitemap-news.xml") is None
        assert c._get_branch_name_from_url("") is None

    def test_mediaindonesia_soft_sections_are_denied_again(self):
        """The regression, pinned end to end: the section the URL carries must
        reach `category_gate` as a deny, not as the mixed bucket `news`."""
        from newscrawler.core.importance_filter import category_gate
        c = CRAWLER_DICT["MEDIAINDONESIA"]
        for url, expected in (
            ("https://mediaindonesia.com/olahraga/936920/jorge-martin-senang", "olahraga"),
            ("https://mediaindonesia.com/hiburan/936913/weird-al-yankovic", "hiburan"),
            ("https://mediaindonesia.com/sepak-bola/936918/timnas-vietnam", "sepak-bola"),
            ("https://mediaindonesia.com/opini/936902/deindustrialisasi", "opini"),
        ):
            section = c._get_branch_name_from_url(url)
            assert section == expected
            assert category_gate(section) == "deny", section
        assert category_gate("news") is None   # what they were being stored as
