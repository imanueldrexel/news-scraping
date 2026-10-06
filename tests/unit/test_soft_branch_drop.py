"""SRC-35 (#128): the soft-vertical deny applied once, in the base Crawler,
to every source's branch keys -- word-bounded so `transportasi` is not
`sport`, with per-crawler exceptions for names a 3-title sample proved are
that outlet's business coverage (table on the ticket)."""
from unittest.mock import MagicMock

import pytest

from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.importance_filter import SOURCE_SOFT_LEAVES, category_gate
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
    def test_kontan_english_and_wartaekonomi_travel_are_dropped_now(self):
        # SRC-52 (#169): their exceptions were undone by the category gate, so the
        # owner removed them; like every other source they drop both.
        assert CRAWLER_DICT["WARTAEKONOMI"].is_soft_branch("travel") is True
        assert CRAWLER_DICT["KONTAN"].is_soft_branch("english") is True
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
        c._get_branches = MagicMock(return_value={"ekonomi": "https://x.example.test/ekonomi.xml",
                                                   "bola": "https://x.example.test/bola.xml"})
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
        for name in ("MEDIAINDONESIA", "MERDEKA", "PIKIRANRAKYAT"):
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
        """The helpers' half: the section a URL carries is a deny, not the mixed
        bucket `news`. This does NOT call `_scrape`, so it cannot catch the
        SRC-48 regression itself (DBT-39 #166: the pre-fix expression passed
        every test while this one claimed to pin it "end to end").
        TestScrapeCategorySelection drives `_scrape`."""
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


class TestCompoundSoftNames:
    """SRC-49 (#160): SYS-42 made the vocabulary word-bounded so `sport` could
    not match `transportasi`. The cost is that a compound name is unreachable --
    `sport` + `setup` is one token. KONTAN listed 27 sports rows under
    `sportsetup` before an anchored prefix was added.

    Found by OPS-19's (#132) first-run `task=sitemap` on the never-crawled
    sources, which is the argument for that step being a prerequisite."""

    @pytest.mark.parametrize("key", [
        "sportsetup", "sportstyle", "sportfeat", "Sportfeat", "sportaliga",
        "sport-lain", "sports", "sport", "sportsbook",
    ])
    def test_a_compound_sport_name_is_dropped_by_the_prefix(self, key):
        assert Crawler.is_soft_branch(key) is True

    @pytest.mark.parametrize("key", ["pop/korean-wave", "korean-wave", "korean", "korea"])
    def test_korean_wave_is_dropped(self, key):
        assert Crawler.is_soft_branch(key) is True

    def test_the_prefix_is_anchored_so_transportasi_survives(self):
        """The whole reason SYS-42 word-bounded the vocabulary. A prefix is safe
        precisely because it is anchored; a substring was not."""
        assert Crawler.is_soft_branch("transportasi") is False
        assert Crawler.is_soft_branch("pariwisata") is False
        assert Crawler.is_soft_branch("passport-services") is False

    def test_exceptions_still_beat_the_prefix(self):
        """An outlet with a genuinely-business `sport*` desk must still be
        keepable with a sample, so the exception check runs first."""
        class SportBusiness(Crawler):
            SOFT_BRANCH_EXCEPTIONS = frozenset({"sportbusiness"})
        assert SportBusiness.is_soft_branch("sportbusiness") is False
        assert SportBusiness.is_soft_branch("sportsetup") is True
        # and it does not leak to other crawlers
        assert Crawler.is_soft_branch("sportbusiness") is True

    def test_no_prefix_collides_with_the_live_not_denied_vocabulary(self):
        """SYS-42's fixture test, extended to prefixes: a prefix that catches a
        live category nobody denied fails here instead of on the next run."""
        import json
        import os
        from newscrawler.infrastructure.datasource.scrapers.crawler import SOFT_BRANCH_PREFIXES
        path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "category_vocabulary_not_denied.json")
        with open(path, encoding="utf-8") as f:
            pairs = json.load(f)["pairs"]
        collisions = [f"{p['source']}/{p['category']}" for p in pairs
                      if p["category"].lower().startswith(SOFT_BRANCH_PREFIXES)]
        assert collisions == [], (
            "a SOFT_BRANCH_PREFIXES entry now catches live categories that were not denied -- "
            "sample their titles before denying them (SRC-39), then update the fixture"
        )

    def test_the_observed_categories_are_denied_for_rows_already_stored(self):
        """The branch fix stops them being listed again; these rows are already
        in `sitemaps`, so the category gate has to reject them."""
        from newscrawler.core.importance_filter import category_gate
        for cat in ("sportsetup", "sportstyle", "korean-wave"):
            assert category_gate(cat) == "deny", cat


class TestSourceSoftLeaves:
    """SRC-50 (#162): soft leaves no vocabulary word reaches, decided per leaf
    from 3 stored titles, denied at BOTH the branch and the category level from
    one definition."""

    QA_NAMED = ["f1", "moto-gp", "raket", "basket", "relationship", "hikmah/doa-dan-hadits",
                "hikmah/khazanah", "hikmah/kisah", "hikmah/muslimah", "tempat-makan", "destination",
                "domestic-destination", "international-destination", "cerita-perjalanan", "jogja/plesir",
                "music", "pop/music", "pop/pensi", "pop/trending", "wedding", "hijab", "diet",
                "sexual-health", "sale-and-shop", "modifikasi"]

    @pytest.mark.parametrize("leaf", QA_NAMED)
    def test_every_leaf_qa_named_is_dropped_and_denied(self, leaf):
        assert CRAWLER_DICT["DETIK"].is_soft_branch(leaf)
        assert category_gate(leaf, "DETIK") == "deny"

    @pytest.mark.parametrize("leaf", ["living", "hikmah/ziswaf", "properti/kepemilikan-rumah", "sumut/budaya",
                                      "bali/budaya", "kendaraan-niaga", "perencanaan-keuangan", "berita",
                                      "jogja/berita", "mobil"])
    def test_mixed_and_empty_leaves_stay_for_the_probe(self, leaf):
        """A leaf is denied only when all 3 titles are soft. `living` is 2 soft + 1
        news (a Lampung woman stranded by the Anak Krakatau eruption); an empty
        leaf has no titles to decide by."""
        assert not CRAWLER_DICT["DETIK"].is_soft_branch(leaf)
        assert category_gate(leaf, "DETIK") != "deny"

    def test_a_source_leaf_is_that_sources_fact_not_a_fleet_rule(self):
        """`f1` is soft on DETIK because DETIK files F1 results there. The branch
        rule is per crawler; nothing else drops a branch called `f1`."""
        others = [n for n, c in CRAWLER_DICT.items() if n != "DETIK" and c.is_soft_branch("f1")]
        assert others == []

    def test_detik_uses_the_shared_set_not_a_copy(self):
        """One definition. A copied literal would drift from the category gate,
        which is SRC-49's two-list bug."""
        assert CRAWLER_DICT["DETIK"].SOFT_BRANCH_DENY is SOURCE_SOFT_LEAVES["DETIK"]

    @pytest.mark.parametrize("name", sorted(CRAWLER_DICT))
    def test_every_crawlers_branch_deny_is_also_a_category_deny(self, name):
        """The mirror, for any crawler that grows a deny set: a branch dropped by
        name but whose stored rows are not denied sends those rows to the probe."""
        crawler = CRAWLER_DICT[name]
        leaked = sorted(k for k in crawler.SOFT_BRANCH_DENY if category_gate(k, name) != "deny")
        assert leaked == []
        assert not (crawler.SOFT_BRANCH_DENY & {e.lower() for e in crawler.SOFT_BRANCH_EXCEPTIONS})

    def test_no_source_leaf_is_a_news_desk(self):
        from newscrawler.core.importance_filter import NEWS_CATEGORIES
        for source, leaves in SOURCE_SOFT_LEAVES.items():
            assert not (leaves & NEWS_CATEGORIES), source

    def test_a_leaf_is_denied_only_for_its_own_source(self):
        """KONTAN lists a `sehat` branch too -- empty on 2026-09-25, so it could not
        be sampled. A fleet-wide `sehat` would have denied it by name alone, which
        is the one thing SRC-39 forbids. The probe that found it:
        scripts/experiments/probe_branch_category_mismatch.py."""
        assert category_gate("sehat", "DETIK") == "deny"
        assert category_gate("sehat", "KONTAN") is None
        assert category_gate("sehat") is None
        assert category_gate("f1", "detik") == "deny", "source match is case-insensitive"

    def test_edutainment_is_no_longer_listed_only_to_be_rejected(self):
        """It was already category-denied through `tainment`; the branch was still
        listed, so every row cost a fetch to be rejected."""
        assert category_gate("edu/edutainment", "DETIK") == "deny"
        assert CRAWLER_DICT["DETIK"].is_soft_branch("edu/edutainment")

    def test_leaves_are_stored_lowercase(self):
        """is_offtopic_category lower-cases the value before the exact match."""
        for leaves in SOURCE_SOFT_LEAVES.values():
            assert all(k == k.strip().lower() for k in leaves)


class TestEveryCallerPassesTheSource:
    """SRC-50: a per-source leaf is denied only when the caller says whose row it
    is. A caller that forgets the source silently disagrees with the live filter
    on exactly those rows, so every production call site must pass it. Checked
    by AST over newscrawler/ and scripts/*.py (tests call the bare form on purpose)."""

    # the positional index the source occupies in each signature
    FUNCTIONS = {"category_gate": 1, "is_offtopic_category": 1}
    METHODS = {"classify_batch": 2, "classify": 2, "is_important": 2}
    # The one intentional bare call: the import-time overlap check against
    # NEWS_CATEGORIES, which is fleet vocabulary by definition.
    ALLOWED = {("newscrawler/core/importance_filter.py", "is_offtopic_category")}

    def _calls(self):
        import ast
        import glob
        import os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        files = glob.glob(os.path.join(root, "newscrawler", "**", "*.py"), recursive=True)
        # Top-level scripts only: scripts/experiments/ are records of a past
        # measurement, several of which score text with no category on purpose.
        files += glob.glob(os.path.join(root, "scripts", "*.py"))
        for path in files:
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                index = self.FUNCTIONS.get(name) if isinstance(f, ast.Name) else self.METHODS.get(name)
                if index is None:
                    continue
                passed = len(node.args) > index or any(k.arg in ("source", "sources") for k in node.keywords)
                yield rel, name, node.lineno, passed

    def test_no_call_site_drops_the_source(self):
        missing = [f"{rel}:{line} {name}" for rel, name, line, passed in self._calls()
                   if not passed and (rel, name) not in self.ALLOWED]
        assert missing == []

    def test_the_guard_sees_the_call_sites_it_claims_to(self):
        """A guard that matches nothing passes forever."""
        seen = {(rel, name) for rel, name, _, _ in self._calls()}
        assert ("newscrawler/domain/services/crawler_service_impl.py", "classify") in seen
        assert ("scripts/reject_denied_categories.py", "category_gate") in seen
        assert ("scripts/train_importance_probe.py", "classify_batch") in seen


def _urlset(*locs):
    body = "".join(
        f"<url><loc>{loc}</loc><news:news><news:publication_date>2026-09-24T10:00:00+07:00"
        f"</news:publication_date><news:title>Judul {i}</news:title></news:news></url>"
        for i, loc in enumerate(locs))
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + body + "</urlset>")


@pytest.fixture
def scrape_with(monkeypatch):
    """Drive a registered crawler's real `_scrape` on a recorded <urlset>; the page
    loader is restored afterwards (CRAWLER_DICT instances are shared)."""
    from bs4 import BeautifulSoup

    def run(name, branch_name, *locs):
        crawler = CRAWLER_DICT[name]
        loader = MagicMock()
        loader.get_soup = lambda url: BeautifulSoup(_urlset(*locs), "xml")
        monkeypatch.setattr(crawler, "page_loader", loader)
        return crawler._scrape("https://example.invalid/%s/sitemap.xml" % branch_name, branch_name)
    return run


class TestScrapeCategorySelection:
    """DBT-39 (#166): SRC-48's regression was ONE expression in `_scrape`, and the
    test that claimed to pin it "end to end" never called `_scrape` -- QA put the
    exact pre-fix expression back and all 1,039 unit tests passed. These call it.

    The pre-SRC-48 expression was
        "category": new_branch_name if branch_name == link else branch_name
    With a real branch name (`news`) the condition is always False, so every row
    was stored as `news`."""

    OLAHRAGA = "https://mediaindonesia.com/olahraga/936490/jadwal-asian-games-2026-hari-ini"
    POLITIK = "https://mediaindonesia.com/politik-dan-hukum/936501/dpr-sahkan-ruu"
    UNNAMEABLE = "https://mediaindonesia.com/936777"

    def test_mediaindonesia_stores_each_articles_own_section_under_a_real_branch_name(self, scrape_with):
        rows = scrape_with("MEDIAINDONESIA", "news", self.OLAHRAGA, self.POLITIK)
        assert [r["category"] for r in rows] == ["olahraga", "politik-dan-hukum"]

    def test_the_stored_soft_section_is_denied_and_the_news_desk_is_not(self, scrape_with):
        rows = scrape_with("MEDIAINDONESIA", "news", self.OLAHRAGA, self.POLITIK)
        gates = [category_gate(r["category"], r["sources"]) for r in rows]
        assert gates == ["deny", "allow"]

    def test_an_unnameable_link_falls_back_to_the_branch_name(self, scrape_with):
        rows = scrape_with("MEDIAINDONESIA", "news", self.UNNAMEABLE)
        assert rows[0]["category"] == "news"

    def test_a_crawler_that_derives_no_section_stores_its_branch_name_never_news(self, scrape_with):
        """The base counterpart: the base `_get_branch_name_from_url` returns the
        constant `news`, which must never win over a real branch name."""
        assert not CRAWLER_DICT["KOMPAS"].derives_category_from_url()
        rows = scrape_with("KOMPAS", "money", "https://money.kompas.com/read/2026/09/24/1/harga-emas")
        assert rows[0]["category"] == "money"


class TestExceptionsSurviveTheCategoryGate:
    """SRC-52 (#169): a SOFT_BRANCH_EXCEPTIONS entry keeps a branch listed, and the
    crawler stores the branch key as the category, so an exception the category
    gate denies only buys a fetch per row before a certain rejection (KONTAN
    `english`: 300 rows, 0 saved). Every exception must survive the gate for its
    own source."""

    @pytest.mark.parametrize("name", sorted(CRAWLER_DICT))
    def test_no_exception_is_denied_at_category_level(self, name):
        crawler = CRAWLER_DICT[name]
        if crawler.derives_category_from_url():
            pytest.skip("stores a per-article section, not the branch key")
        undone = sorted(k for k in crawler.SOFT_BRANCH_EXCEPTIONS if category_gate(k, name) == "deny")
        assert undone == []


def test_gridid_is_retired_everywhere():
    """SRC-37 (#130) / SRC-52: registered nowhere (the SYS-31 deny entries for its
    brands stay, and so do its stored rows)."""
    import importlib.util
    import os
    from newscrawler.core.crawler_url_list import WEB_URL_DICT
    from newscrawler.domain.entities.extraction.url_data import URL
    from newscrawler.domain.entities.extraction.website_name import WebsiteName
    assert "GRIDID" not in CRAWLER_DICT and "GRIDID" not in WEB_URL_DICT
    assert "GRIDID" not in WebsiteName.__members__ and "GRIDID" not in URL.__members__
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    spec = importlib.util.spec_from_file_location("nm", os.path.join(root, "__main__.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "GRIDID" not in mod.HEALTHY
    assert not os.path.exists(os.path.join(root, "newscrawler", "infrastructure", "datasource", "scrapers", "grid_id"))
