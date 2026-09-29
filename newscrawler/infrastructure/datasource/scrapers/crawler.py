import collections
import logging
import os
import re
import threading
from newspaper import Article
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Dict, Optional, Union, Any, Tuple
from urllib.parse import urlparse

import pydantic

from newscrawler.core.constants import VERBOSE, PARALLELIZE, MAX_WORKER, MIN_ARTICLE_CHARS
from newscrawler.core.page_loader.throttle import NOT_FETCHED_REASON, ThrottleGuard
from newscrawler.core.page_loader.page_loader import PageLoader
from newscrawler.core.page_loader.requests_page_loader import RequestsPageLoader
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.utils.date_time_reader import DateTimeReader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-52 (#178): the scheduled worker died natively in lxml (etree.pyd,
# 0xC0000005) while PIKIRANRAKYAT -- whose own selector finds nothing, so every
# page goes through trafilatura -- ran the fallback on up to 32 fetch threads at
# once. lxml documents its compiled XPath evaluators as not thread-safe, and
# trafilatura keeps them at module level. The fallbacks' parse runs under this
# lock; the network fetch stays parallel. Measured on 480 extractions: locked
# 33 s vs threaded 32 s (EXPERIMENTS.md 2026-09-26 QA entry), so it costs nothing.
LXML_PARSE_LOCK = threading.Lock()


class NewsDetailsBatch(list):
    """What batch_crawling_details has always returned -- the NewsDetailsDTOs that
    were fetched and extracted, in order -- plus, since OPS-15, WHY each of the
    other sitemaps in the batch produced nothing: `failures` maps sitemap_id to a
    short reason ("HTTP 404", "ReadTimeout after 5 retries", "soft-404: ...", an
    exception name from the extractor). len()/iteration/indexing are unchanged
    for every existing caller; the service layer reads `failures` to store a real
    sitemaps.last_fetch_error instead of one constant string for everything.
    Same shape as SitemapSaveResult (SYS-07)."""

    def __init__(self, items=(), failures: Optional[Dict[int, str]] = None):
        super().__init__(items)
        self.failures: Dict[int, str] = dict(failures or {})


class SitemapScrapeBatch(list):
    """What batch_crawling_sitemap has always returned (a SitemapDTO per scraped
    entry) -- len()/iteration/indexing unchanged for every existing caller.
    SYS-32: additionally carries how many entries were dropped for having no
    usable publication date (neither news:publication_date nor lastmod), so
    crawl_sitemaps can log that count next to new_count instead of the drop
    being invisible. Same shape as NewsDetailsBatch/SitemapSaveResult."""

    def __init__(self, items=(), skipped_no_date: int = 0):
        super().__init__(items)
        self.skipped_no_date: int = skipped_no_date


# SRC-35 (#128) / SRC-39 (#133): the soft verticals, dropped at branch level
# for every source, before a single URL of them is listed. Under the
# news-worthy scope the branch list IS the scope decision for a source, and it
# belongs in one place rather than in twenty `_get_branches` bodies.
#
# Every name here was decided from a 3-title sample of the live branch on
# 2026-09-22 (scripts/experiments/sample_branch_titles.py; table on SRC-35),
# never from the name. What the samples KEPT, and is therefore deliberately
# NOT here: `teknologi`/`tekno`/`ototekno`/`tekno-sains` (Apple, an AI summit,
# Nvidia, a NASA meteor analysis -- tech news is news; gadget *reviews* are
# the probe's job), `kesehatan` (TRIBUN: MBG poisoning victims; WARTAEKONOMI:
# Ebola, BPJS), `otomotif` (SINDONEWS/JPNN/WARTAEKONOMI: Toyota global sales,
# EV market share, dealer expansion -- SYS-31 sampled the same and kept it),
# `transportasi` (WARTAEKONOMI: toll traffic, ganjil-genap -- and the `sport`
# trap it is famous for), `edukasi`, `syariah`, `muslim` (haji registration).
#
# SRC-45 (#155, 2026-09-23) revisited the one entry that did not survive
# re-measurement: `video`/`foto` were kept here on 2026-09-22 as "IDXCHANNEL:
# IHSG analysis, the Menkeu handover". Measuring the extracted body split them
# -- IDXCHANNEL `foto` is 597/842 chars of real reporting and is now a
# SOFT_BRANCH_EXCEPTION on that crawler, while `video` is 205/198 chars of
# caption on a player. The words are in the list below; the evidence-backed
# keeps are per-crawler exceptions.
#
# Matching is word-bounded on the separators a branch key actually uses
# (`-`, `_`, `/`, `.`), so `transportasi` never matches `sport` while
# `bali/sport` does. A per-crawler SOFT_BRANCH_EXCEPTIONS set keeps a name
# whose sample proved it is that outlet's business coverage.
# SRC-49 (#160): a soft vertical whose name is a COMPOUND word is unreachable by
# the word-bounded vocabulary -- `sport` + `setup` is one token, so
# `is_soft_branch("sportsetup")` was False and KONTAN listed 27 sports rows
# (Man Utd vs Man City, MMA medals at the Asian Games) that then went to the
# probe instead of being denied. Enumerating variants does not scale; the
# existing literal `sportaliga` in the vocabulary below is the previous attempt.
#
# A PREFIX is safe here, and was measured before being added: `^sport` matches 15
# live branch keys across the fleet and **every one is sports** (`sport`,
# `sport-lain`, `sportstyle`, `Sportfeat`, `sportsetup`, `sports/*`, `Sportaliga`,
# `sports`), and collides with **0** pairs in
# tests/fixtures/category_vocabulary_not_denied.json. Critically it is anchored,
# so `transportasi` -- the SYS-42 false positive this whole boundary exists for --
# does not start with `sport` and is untouched.
#
# Checked AFTER SOFT_BRANCH_EXCEPTIONS, so an outlet with a genuinely-business
# `sport*` desk can still be kept with a 3-title sample.
SOFT_BRANCH_PREFIXES = ("sport",)

SOFT_BRANCH_WORDS = (
    # sport (owner decision 2026-09-20: out)
    "sport", "sports", "esport", "esports", "olahraga", "bola", "sepakbola", "sepak-bola",
    "bolasport", "bolanita", "bolastylo", "bolanas", "superskor", "sportaliga", "piala", "juara",
    # entertainment / celebrity / music / film
    "showbiz", "seleb", "selebriti", "celeb", "celebs", "celebrity", "hiburan", "entertainment",
    # SRC-49: `korean` as a word -- DETIK's key is `pop/korean-wave`, so `korea`
    # word-bounded cannot reach it ("korea" is followed by "n") and a `^korea`
    # prefix matches 0 live keys. Sampled: "Teaser Comeback Kim Woo Bin di
    # Drakor", "Lee Min Ho Saingan Berat Byun Yo Han" -- the IDNTIMES `korea`
    # class SYS-34 already denies.
    "hype", "kpop", "korea", "korean", "musik", "film", "filmon", "movie", "sinetron", "klikseleb",
    "idxtainment", "ecotainment", "entertainment_life_style",
    # lifestyle / fashion / beauty / women & parenting
    "lifestyle", "gaya-hidup", "gayahidup", "fashion", "beauty", "kecantikan", "stylo", "jelita",
    "women", "woman", "mom", "momandkids", "cewekbanget", "nakita", "nova",
    # food / travel
    "kuliner", "sajian", "resep", "food", "travel", "wisata", "destinasi", "piknik", "travelista",
    # religion guides (doa, tausiyah, daily reflections). NOTE (SRC-35): the
    # SINDONEWS `kalam` and JPNN `ramadan` samples were haji operations and
    # mudik logistics -- news by the rubric, denied by the SYS-31 category
    # list today, so dropping the branch changes nothing observable. Recorded
    # on the ticket for SYS-37's probe to revisit; do not "fix" it here.
    "religi", "ramadan", "kalam",
    # games / quizzes / horoscopes / fiction / photo and gadget gear
    "games", "game", "quiz", "horoskop", "zodiak", "fiction", "puisi", "gridgames",
    "fotostop", "konsultasifotografi", "konsultasigadget", "gadget",
    # hobby magazines (GRIDID's network, SRC-37) and user/PR columns
    "bobo", "intisari", "fotokita", "gridhealth", "gridoto", "motorplus", "otoseken", "hai",
    "idea", "donwori", "advetorial", "advertorial", "siaran-pers", "vstory", "blog",
    # opinion / analysis / editorial columns (SYS-49 #147, owner 2026-09-23):
    # an op-ed argues about an event, it is not one. Dropped here so the
    # section is never listed, and denied at category level for the rows
    # already in `sitemaps`. Sampled 4 titles each -- CNBC/JPNN `opini`,
    # MEDIAINDONESIA `editorials`/`kolom-pakar`/`surat-pembaca`,
    # SINDONEWS `scope` (table on SYS-49). `analisis` is deliberately absent.
    "opini", "opinion", "editorial", "editorials", "kolom", "kolom-pakar",
    "tajuk", "tajuk-rencana", "surat-pembaca", "scope",
    # photo galleries and video pages -- a page whose content is the medium,
    # not an article (SRC-45 #155, owner decision 2026-09-23: "exclude
    # archives, galleries, photos"). Decided by SUBSTANCE, not by the name:
    # every leaf below was sampled and its extracted body measured through the
    # source's own `_get_whole_text` (table on SRC-45).
    #   DROPPED: MEDIAINDONESIA `gallery-YYYY-MM` (365/370 chars of caption on
    #     `detail_galleries` pages) and `video` (`detail_video` pages);
    #     IDXCHANNEL `video` (205/198 chars of caption on a player -- below or
    #     at MIN_ARTICLE_CHARS=200); GRIDID `Video`.
    #   KEPT as SOFT_BRANCH_EXCEPTIONS, because the sample says they are
    #     ordinary reporting that merely sits under a medium's name:
    #     IDXCHANNEL `foto` (597/842: "Komisi V DPR Setujui Anggaran Kemendes
    #     PDT Rp2,785 Triliun") and `infografis`; BERITASATU `multimedia`
    #     (759/899: "Babak Akhir BLBI: Utang Rp 640 Triliun Lunas"); VIVA
    #     `viva-visual` (1157/2514). `multimedia`, `visual`, `infografis` and
    #     `tv` are therefore deliberately NOT in this list -- on this corpus
    #     their default meaning is news, so a blanket name rule would be the
    #     `transportasi`/`sport` false positive again.
    "gallery", "galleries", "galeri", "video", "foto", "photo",
    # duplicate translations of a desk we already list (KONTAN's market wire
    # is the exception -- see its crawler)
    "english", "english_edition",
    # SRC-43 (#146): DETIK's English edition lives on its own domain, so it
    # never carried the word `english` in its key. Sampled 2026-09-23 --
    # "Influenza Cases Rise in Indonesia", "Update on KM Virgo SAR: 18 Dead",
    # "Anak Krakatau Status Downgraded": real news, in English, duplicating
    # desks we already list. Same ground as `english` above.
    "indonesianow",
)


# SRC-45 (#155): a YYYY-MM calendar partition in a branch key -- `article-2026-09`,
# `gallery-2026-09`, `arsip/2015-02`. Bounded by a non-digit so a bare year or an
# id like `12345-6` cannot match.
_ARCHIVE_PARTITION_RE = re.compile(r"(?:^|[^0-9])(?:19|20)\d{2}[-_/.]\d{1,2}(?:[^0-9]|$)")

# DBT-38 (#159): both drop lists get the same cap. SRC-45 capped only the
# archive list, but `is_soft_branch` is evaluated first, so MEDIAINDONESIA's 140
# `gallery-YYYY-MM` partitions match the word `gallery` and land in the SOFT
# list -- which logged all 141 names on one ~2 KB line, hiding the single
# interesting entry in it (`video`). The cap belongs on whichever list can grow,
# and that is decided by evaluation order, not by intent.
_LOG_SAMPLE = 5


def _summarise(keys) -> str:
    names = sorted(keys)
    head = ", ".join(names[:_LOG_SAMPLE])
    return head + (f" ... +{len(names) - _LOG_SAMPLE} more" if len(names) > _LOG_SAMPLE else "")


class Crawler:
    # SRC-35: names this crawler keeps although they are in SOFT_BRANCH_WORDS,
    # because a 3-title sample proved they are that outlet's business or news
    # coverage. Every entry cites its evidence on SRC-35 (#128).
    SOFT_BRANCH_EXCEPTIONS = frozenset()
    # SRC-50 (#162): exact branch keys this crawler drops although no vocabulary
    # word is in them (DETIK's `f1`, `relationship`). Point it at
    # `importance_filter.SOURCE_SOFT_LEAVES[<source>]`, never a local literal:
    # that set is also what the category gate denies, and a copy is SRC-49's
    # two-list drift again (a test enforces the mirror).
    SOFT_BRANCH_DENY = frozenset()
    # SRC-38 (#131): sitemap indexes this source publishes besides `website_url`.
    # KOMPAS has three (news., money., www.); every other source has one. Their
    # branches are merged into the primary index's by `list_branches`, the primary
    # winning a key collision.
    EXTRA_INDEX_URLS = ()
    # DBT-05 (#24): which extractor produces this source's article text.
    # "site" -- the subclass's `_get_whole_text` selectors, trafilatura and
    # newspaper only as fallbacks. "trafilatura" -- no site selector exists or
    # runs; trafilatura is the extractor by design, newspaper its fallback.
    # Measured 2026-09-29 (EXPERIMENTS.md "DBT-05: extractor order"): where a
    # selector works it is as good or more precise than trafilatura (JPNN,
    # MEDIAINDONESIA, EMITENNEWS, TRIBUN, SINDONEWS), so it stays; where it had
    # been dead for months, trafilatura was already producing every article.
    # check_crawlers.py reports FALLBACK only when the declared one did not win.
    PRIMARY_EXTRACTOR = "site"

    def __init__(self):
        self.verbose = VERBOSE
        self.parallelize = PARALLELIZE
        self.date_time_reader = DateTimeReader()
        self.main_path = os.path.dirname(os.path.realpath(__file__))
        self.default_time = self.date_time_reader.convert_date("2000-01-01 00:00:01")
        self.max_worker = MAX_WORKER
        self.page_loader = RequestsPageLoader()
        self.website_url = None
        self.website_name = None

    def batch_crawling_sitemap(
        self, news: List[Dict[str, str]], website_name: str
    ) -> "SitemapScrapeBatch":
        news_data = SitemapScrapeBatch()
        if news:
            if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
                with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                    results = list(executor.map(self._get_sitemap, news))
            else:
                results = [self._get_sitemap(n) for n in news]

            # SYS-32: a lastmod-only sitemap (no news:publication_date) drops
            # here -- one summary WARNING per branch instead of one exception
            # log line per <url>. `category` on the raw dict is the branch name
            # `_scrape` stamped on every entry.
            skipped_by_branch = collections.Counter()
            for n, result in zip(news, results):
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)
                elif n.get("timestamp") is None:
                    skipped_by_branch[n.get("category") or "unknown"] += 1
            for branch, count in skipped_by_branch.items():
                logger.warning(
                    f"{website_name}/{branch}: {count} entries had no usable "
                    f"publication date (no news:publication_date or lastmod), skipped"
                )
            news_data.skipped_no_date = sum(skipped_by_branch.values())

        return news_data

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        raise NotImplementedError

    # SRC-48 (#158): the longest a derived section name may be before we assume
    # the extraction failed and fall back to the branch name.
    MAX_CATEGORY_LEN = 40

    @staticmethod
    def _get_branch_name_from_url(url) -> str:
        return "news"

    @classmethod
    def derives_category_from_url(cls) -> bool:
        """SRC-48: does this crawler actually implement a per-article section?

        The base returns the constant "news", which is strictly worse than a
        real branch name, so only a subclass's own implementation is used. This
        replaces `branch_name == link` in `_scrape`, which tested whether the
        crawler could name its BRANCH -- an unrelated question that tied the
        two together, so SRC-43 (#146) naming MEDIAINDONESIA's branches silently
        stopped its per-article section from ever being consulted."""
        return cls._get_branch_name_from_url is not Crawler._get_branch_name_from_url

    @classmethod
    def usable_section_name(cls, value) -> bool:
        """SRC-48: a derived category we are willing to store.

        A broken extractor must degrade to the branch name, never write a URL
        into `sitemaps.category` -- that is the SRC-36/SRC-41 damage (6,104
        rows repaired) and `category_gate` cannot read it. MEDIAINDONESIA's
        override returned its input unchanged for exactly this reason."""
        v = (value or "").strip()
        return bool(v) and not v.lower().startswith("http") and len(v) <= cls.MAX_CATEGORY_LEN

    @classmethod
    def is_archive_branch(cls, branch_key: str) -> bool:
        """SRC-45 (#155): a branch keyed by a calendar partition is a
        back-catalogue, not a section -- MEDIAINDONESIA publishes
        `article-2026-09` and `gallery-2026-09` for every month back to
        2015-02, 280 partitions and roughly 1.24 million URLs against the 904
        in its `news` sitemap.

        This is a SHAPE, not a vocabulary word, which is why it is its own
        rule: "archive" is a structural property of the key, and writing
        `article` into SOFT_BRANCH_WORDS would deny the most ordinary section
        name there is on every other source. It is fleet-general on purpose --
        any source that starts publishing month partitions is covered the day
        it does, without another ticket.

        A bare year is NOT an archive: `piala-dunia-2026` is a tournament desk
        (already soft for other reasons) and a year alone is too common in a
        section name to be evidence. The partition must be YYYY-MM."""
        key = (branch_key or "").strip().lower()
        return bool(_ARCHIVE_PARTITION_RE.search(key))

    @classmethod
    def is_soft_branch(cls, branch_key: str) -> bool:
        """SRC-35 (#128): True when this branch is a soft vertical for this
        crawler. Word-bounded on the separators branch keys use, so
        `transportasi` is never `sport` and `bali/sport` is; a key this
        crawler lists in SOFT_BRANCH_EXCEPTIONS is always kept."""
        key = (branch_key or "").strip().lower()
        if not key:
            return False
        if key in {e.lower() for e in cls.SOFT_BRANCH_EXCEPTIONS}:
            return False
        if key in cls.SOFT_BRANCH_DENY:
            return True
        # SRC-49: the anchored prefixes catch compound names the word-bounded
        # vocabulary cannot reach (`sportsetup`, `sportstyle`). Exceptions above
        # still win, and being anchored it cannot repeat the `transportasi` bug.
        if key.startswith(SOFT_BRANCH_PREFIXES):
            return True
        return any(
            re.search(rf"(?:^|[^a-z0-9]){re.escape(word)}(?:[^a-z0-9]|$)", key)
            for word in SOFT_BRANCH_WORDS
        )

    def drop_soft_branches(self, branches: Dict[str, str]) -> Dict[str, str]:
        """SRC-35: the scope decision for a source, applied once for every
        crawler after its own `_get_branches`. Dropped keys are logged once per
        run, so a site adding a vertical is visible the day it appears.

        SRC-45 (#155) adds the archive rule. The two reasons are logged
        separately and the archive list is summarised rather than enumerated --
        MEDIAINDONESIA alone drops 280 partitions, and a 280-name log line
        would bury the soft-vertical list that is actually worth reading."""
        kept, dropped, archived = {}, [], []
        for key, link in (branches or {}).items():
            if self.is_soft_branch(key):
                dropped.append(key)
            elif self.is_archive_branch(key):
                archived.append(key)
            else:
                kept[key] = link
        if dropped:
            logger.info(
                f"{self.website_name}: dropped {len(dropped)} soft branch(es) before listing "
                f"(SRC-35): {_summarise(dropped)}"
            )
        if archived:
            logger.info(
                f"{self.website_name}: dropped {len(archived)} archive partition(s) before listing "
                f"(SRC-45): {_summarise(archived)}"
            )
        return kept

    def extra_index_branches(self) -> Dict[str, str]:
        """SRC-38: branches from EXTRA_INDEX_URLS. An extra index that does not
        load is logged and skipped, since the primary index still stands."""
        merged: Dict[str, str] = {}
        for url in self.EXTRA_INDEX_URLS:
            soup = self.page_loader.get_soup(url)
            if not soup:
                logger.warning(f"{self.website_name}: could not load extra sitemap index {url}")
                continue
            for key, link in (self._get_branches(soup) or {}).items():
                merged.setdefault(key, link)
        return merged

    def list_branches(self) -> Optional[Dict[str, str]]:
        """Every branch this source lists, across all its indexes, BEFORE the soft
        drop -- or None when the primary index does not load. The one place that
        answers "what does this source list" (get_news_in_bulk and the probes)."""
        soup = self.page_loader.get_soup(self.website_url)
        if not soup:
            return None
        branches = dict(self._get_branches(soup) or {})
        for key, link in self.extra_index_branches().items():
            branches.setdefault(key, link)
        return branches

    def get_news_in_bulk(self) -> List:
        listed = self.list_branches()
        if listed is None:
            logger.warning(f"Could not load sitemap from {self.website_url}")
            return []

        branches_to_crawl = self.drop_soft_branches(listed)
        links_to_crawl = []

        for branch_name, branch_link in branches_to_crawl.items():
            links = self._scrape(branch_link=branch_link, branch_name=branch_name)
            links_to_crawl.extend(links)
        return links_to_crawl

    def _scrape(self, branch_link, branch_name) -> List:
        logger.info(f"Scrape {branch_name} on {self.website_name}")
        soup = self.page_loader.get_soup(branch_link)
        articles = []
        if soup is None:
            return articles
        else:
            for idx, url in enumerate(soup.find_all("url")):
                link = self._get_link(url)
                title = self._get_title(url)
                keywords = self._get_keywords(url)
                timestamp_datetime = self._get_timestamp(
                    url, date_time_reader=self.date_time_reader
                )
                new_branch_name = self._get_branch_name_from_url(link)
                attributes = {
                    "link": link,
                    "headline": title,
                    "keywords": keywords,
                    "timestamp": timestamp_datetime,
                    # SRC-48 (#158): prefer the article's own section when this
                    # crawler derives one and the value is usable; otherwise the
                    # branch name. The old test was `branch_name == link`, i.e.
                    # "this crawler could not name its branch" -- which SRC-43
                    # made permanently false for MEDIAINDONESIA, so every row
                    # became `news` and the deny-list stopped seeing its
                    # olahraga/hiburan content.
                    "category": (
                        new_branch_name
                        if self.derives_category_from_url() and self.usable_section_name(new_branch_name)
                        else branch_name
                    ),
                    "sources": self.website_name,
                }
                articles.append(attributes)
            return articles

    @staticmethod
    def _get_whole_text(soup):
        pass

    @staticmethod
    def _get_sitemap(articles_data: Dict[str, Any]) -> Union[SitemapDTO, None]:
        # SYS-32: a lastmod-only leaf (TIRTO, TEMPO, BATAMPOS) has no
        # news:publication_date -- there is nothing to fall back to for a
        # sitemap row (unlike the timestamp, lastmod is not itself a
        # publication date), so drop it before it ever reaches pydantic's
        # NOT NULL-equivalent validation. batch_crawling_sitemap aggregates
        # this into one WARNING per branch instead of an exception per row.
        if articles_data.get("timestamp") is None:
            return None
        try:
            data_field_dict = {
                field: None for field in SitemapDTO.__dataclass_fields__.keys()
            }
            # sitemaps.headline is NOT NULL; a lastmod-only leaf has no
            # news:title either, so fall back to a slug derived from the URL
            # rather than lose the row -- _get_news_details prefers a real
            # page title over this placeholder when one is available.
            data_field_dict["headline"] = articles_data.get("headline") or Crawler._derive_headline_from_url(
                articles_data.get("link")
            )
            data_field_dict["keywords"] = articles_data.get("keywords")
            data_field_dict["timestamp"] = articles_data.get("timestamp")
            data_field_dict["category"] = articles_data.get("category")
            data_field_dict["link"] = articles_data.get("link")
            data_field_dict["sources"] = articles_data.get("sources")
            return SitemapDTO(**data_field_dict)
        except BaseException as e:
            logger.info(
                f"Error in get_content {articles_data.get('link')}. Reason: {e}"
            )
            return None

    @staticmethod
    def _derive_headline_from_url(link: Optional[str]) -> Optional[str]:
        """SYS-32: fallback for sitemaps.headline (NOT NULL) when the sitemap
        entry has no news:title. A news URL's slug is usually the headline in
        kebab-case ("daftar-lengkap-harga-bbm-pertamina-per-1-september-2026-hB7q"),
        so turning it into words is a serviceable placeholder -- not the real
        headline, but enough for the row to save and for the semantic filter to
        have something to score."""
        if not link:
            return None
        slug = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.(html?|xml|php)$", "", slug, flags=re.IGNORECASE)
        slug = slug.replace("-", " ").replace("_", " ").strip()
        return slug.title() if slug else None

    @staticmethod
    def _get_timestamp(news_soup, date_time_reader: DateTimeReader):
        timestamp = news_soup.find("news:publication_date")
        if not timestamp:
            # SYS-32: sitemaps.org leaves with no news: namespace (TIRTO,
            # TEMPO, BATAMPOS) carry only <lastmod>. It is not the true
            # publication date, but it is the newest signal available and the
            # only way these sources save any row at all.
            timestamp = news_soup.find("lastmod")
        if timestamp:
            timestamp_string = timestamp.get_text(" ").strip()
            # SYS-11: convert_date() already returns the correct +07:00 (WIB)
            # instant -- re-expressing it in UTC here (date_time_reader.gmt_offset)
            # shifted an article's stored calendar day backwards whenever it was
            # published 00:00-06:59 WIB, since every downstream posted_at is
            # int(dt.strftime("%Y%m%d")) on whatever tzinfo this method hands back.
            # Return the WIB instant unchanged, matching what emitennews_crawler.py
            # and antara_news_crawler.py's own _get_timestamp overrides already do
            # (the latter independently avoiding this exact bug, the former with an
            # explicit comment about it).
            return date_time_reader.convert_date(timestamp_string)

    @staticmethod
    def _get_title(news_soup, news_title_element_name: str = "news:title") -> str:
        title = news_soup.find(news_title_element_name)
        if title:
            title = title.get_text(" ").strip()
            return title

    def _get_link(self, news_soup) -> str:
        link = news_soup.find("loc")
        if link:
            link = link.get_text(" ").strip()
            if "?page=all" not in link and self.website_name != "JPNN":
                link += "?page=all"
            return link

    @staticmethod
    def _get_keywords(news_soup) -> List[str]:
        keyword_div = news_soup.find("news:keywords")
        if keyword_div:
            keywords = keyword_div.get_text(" ").strip()
            # SYS-22 (#43): <news:keywords> is a comma-separated list per the
            # Google News sitemap spec, and every outlet emits it that way. A
            # whitespace split turned "Badan Gizi Nasional (BGN), Makan Bergizi
            # Gratis (MBG)" into eight word tokens with commas glued on, which
            # destroyed every multi-word entity the column exists to carry.
            keywords = [x.strip() for x in keywords.split(",") if x.strip()]
            return keywords

    def batch_crawling_details(
        self, news: List[SitemapDTO], website_name: str, throttle: Optional[ThrottleGuard] = None
    ) -> "NewsDetailsBatch":
        """SRC-55: with a `throttle` guard (one per source run, shared by its
        batches), every finished fetch is recorded on it, and once it trips the
        fetches not yet started are skipped with NOT_FETCHED_REASON."""
        news_data = NewsDetailsBatch()
        if news:
            fetch = self._fetch_news_details
            if throttle is not None:
                def fetch(sitemap):
                    if not throttle.should_fetch():
                        return None, NOT_FETCHED_REASON
                    result, reason = self._fetch_news_details(sitemap)
                    throttle.record(sitemap.sitemap_id, None if result else reason)
                    return result, reason
            if self.parallelize and website_name != WebsiteName.MEDIAINDONESIA.value:
                with ThreadPoolExecutor(max_workers=self.max_worker) as executor:
                    results = list(executor.map(fetch, news))
            else:
                results = [fetch(n) for n in news]

            for sitemap, (result, reason) in zip(news, results):
                if result:
                    if self.verbose:
                        logger.info(result)
                    news_data.append(result)
                else:
                    news_data.failures[sitemap.sitemap_id] = reason or "fetch or extraction produced no result"

        return news_data

    def _get_news_details(self, sitemap: SitemapDTO) -> NewsDetailsDTO:
        return self._fetch_news_details(sitemap)[0]

    def _load_page(self, url: str):
        """(soup, reason) from the page loader. A real PageLoader reports why a fetch
        failed (OPS-15); anything else assigned to page_loader -- an object that only
        implements get_soup, including every test double -- gets the generic reason."""
        if isinstance(self.page_loader, PageLoader):
            return self.page_loader.get_soup_with_reason(url)
        soup = self.page_loader.get_soup(url)
        return (soup, None) if soup else (None, "page loader returned no document")

    def _fetch_news_details(self, sitemap: SitemapDTO) -> Tuple[Optional[NewsDetailsDTO], Optional[str]]:
        """(dto, None) on success; (None, reason) when the page could not be fetched
        or anything in the extraction path raised. OPS-15: the reason is what the
        service layer stores in sitemaps.last_fetch_error, so it must say what
        actually happened (HTTP status, timeout, soft-404, exception type) -- the
        log line alone was never queryable."""
        try:
            url = sitemap.link
            if self.website_name == "JPNN":
                url = sitemap.link.replace("?page=all", "")
            soup, fetch_reason = self._load_page(url)
            if soup is None:
                return None, fetch_reason or "page loader returned no document"
            if soup:
                # Site extractors are hand-written selectors that raise (typically
                # AttributeError on a missing container) when the layout drifts. A crash
                # must count as "extractor failed", not discard the article, so the
                # fallback chain still runs and the sitemap still gets marked attempted.
                try:
                    reporter = self._get_reporter_from_text(soup)
                    # SRC-10 (#65): a hand-written selector can drift onto a
                    # timestamp/id element instead of the byline (IDXCHANNEL's
                    # matched the publication day, storing writer=["16"] on every
                    # row) and still return a non-empty, plausible-looking string --
                    # no "missing byline" check can catch that. Drop any candidate
                    # that is purely digits or parses as a date, across every
                    # crawler, not just the one caught so far.
                    reporter = [r for r in reporter if self._looks_like_a_name(r)]
                except Exception as r_err:
                    logger.warning(f"Reporter extraction raised for {url}: {r_err!r}")
                    reporter = []
                # OPS-02: track which extractor's output actually won, so "OK" in
                # check_crawlers.py can be told apart from "the site selector is dead
                # and a fallback is quietly doing all the work".
                if self.PRIMARY_EXTRACTOR == "trafilatura":
                    # DBT-05 (#24): no site selector for this source; trafilatura is
                    # its extractor by design, newspaper below its fallback.
                    extracted_text = self._trafilatura_fallback(soup)
                    extractor_used = "trafilatura"
                else:
                    try:
                        extracted_text = self._get_whole_text(soup)
                    except Exception as x_err:
                        logger.warning(f"Site extractor raised for {url}: {x_err!r}")
                        extracted_text = None
                    extractor_used = "site"

                    # Site extractors return None when their container is missing and []
                    # when it exists but no paragraph matched (layout drift). Both, and
                    # anything shorter than MIN_ARTICLE_CHARS, fall through to the next
                    # extractor.
                    if not self._has_usable_text(extracted_text):
                        logger.info(f"Standard extraction failed for {url}. Attempting Trafilatura fallback...")
                        trafilatura_text = self._trafilatura_fallback(soup)
                        combined = self._best_of(extracted_text, trafilatura_text)
                        if trafilatura_text is not None and combined is trafilatura_text:
                            extractor_used = "trafilatura"
                        extracted_text = combined

                if not self._has_usable_text(extracted_text):
                    newspaper_text = self._newspaper_fallback(url)
                    combined = self._best_of(extracted_text, newspaper_text)
                    if newspaper_text is not None and combined is newspaper_text:
                        extractor_used = "newspaper"
                    extracted_text = combined

                if not self._has_usable_text(extracted_text):
                    logger.warning(
                        f"All extractors returned empty or too-short text for {url} "
                        f"({self._text_length(extracted_text)} chars)"
                    )
                    extractor_used = None

                # The DTO requires a list. Leaving None here made the DTO fail validation,
                # which returned None from this method and left the sitemap unmarked --
                # the retry-forever loop SYS-02 was meant to close.
                if extracted_text is None:
                    extracted_text = []
                elif isinstance(extracted_text, str):
                    extracted_text = [extracted_text] if extracted_text.strip() else []

                # SYS-33 (#114): a lastmod-only leaf (TIRTO, TEMPO) never has a
                # news:title, so _get_sitemap stored the URL slug as the
                # headline -- trailing id included ("... Ini Pergerakannya
                # Hca5"). SYS-32 wired _get_page_title behind
                # `sitemap.headline or ...`, which its own fallback made
                # unreachable on the live path: 317 articles kept the slug as
                # their permanent title (filter input, FAISS metadata, UI).
                # Now the page's og:title wins whenever the stored headline is
                # that placeholder (or empty); the service writes it back to
                # sitemaps.headline (`headline_from_page`), rejected rows too.
                title = sitemap.headline
                headline_from_page = False
                if not title or self._is_placeholder_headline(sitemap):
                    page_title = self._get_page_title(soup)
                    if page_title:
                        title = page_title
                        headline_from_page = True
                meta_data = {
                    "title": title,
                    "posted_at": sitemap.timestamp,
                    "extractor": extractor_used,
                    "headline_from_page": headline_from_page,
                }
                return NewsDetailsDTO(
                    sitemap_id=sitemap.sitemap_id,
                    extracted_text=extracted_text,
                    reporter=reporter,
                    meta_data=meta_data,
                ), None
            # A BeautifulSoup with no content is falsy; nothing to extract from.
            return None, "empty document"
        except BaseException as e:
            logger.info(f"Error in get_content {sitemap.link}. Reason: {e}")
            return None, f"{type(e).__name__}: {e}"[:200]

    @staticmethod
    def _slug_has_id_tail(link: str) -> bool:
        """The slug of a lastmod-only outlet's URL ends in an article id --
        TIRTO "-hCa5"/"-hCth" (4 chars, mixed case), TEMPO "-2287141" (digits).
        A real slug is lowercase words, so a last token with a digit or an
        upper-case letter is an id; a bare year ("-pilkada-2024") is not."""
        slug = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.(html?|xml|php)$", "", slug, flags=re.IGNORECASE)
        tail = slug.rsplit("-", 1)[-1] if "-" in slug else ""
        if not tail or re.fullmatch(r"(19|20)\d{2}", tail):
            return False
        return bool(re.search(r"\d", tail) or re.search(r"[A-Z]", tail))

    @classmethod
    def _is_placeholder_headline(cls, sitemap: SitemapDTO) -> bool:
        """SYS-33: True when the stored headline is what _derive_headline_from_url
        made of the link -- i.e. it came from the SYS-32 slug fallback, not from
        a news:title. Detected rather than carried as a flag so a DTO rebuilt
        from a DB row (the live full_text path loads sitemaps back from
        Postgres) is recognised too.

        Equality alone is not enough: 3,580 genuine headlines on MEDIAINDONESIA,
        JPNN, INEWS, KOMPAS, ... are short, punctuation-free Title Case and
        coincide with their own slug ("Keadilan Terkubur Longsor"). The
        placeholder additionally carries the URL's trailing id token, which a
        real headline does not, so both conditions are required."""
        if not sitemap.headline or not sitemap.link:
            return False
        if sitemap.headline != cls._derive_headline_from_url(sitemap.link):
            return False
        return cls._slug_has_id_tail(sitemap.link)

    @staticmethod
    def _get_page_title(soup) -> Optional[str]:
        """SYS-32/SYS-33: headline source when sitemap.headline is empty or a
        URL-slug placeholder -- og:title first (more curated than the raw
        <title> tag, which often carries a " | SiteName" suffix), then <title>
        itself."""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(" ").strip()
        return None

    @staticmethod
    def _text_length(extracted_text) -> int:
        """Total characters in an extraction result (None, str, or list of paragraphs)."""
        if not extracted_text:
            return 0
        if isinstance(extracted_text, str):
            return len(extracted_text.strip())
        return sum(len(p.strip()) for p in extracted_text if p)

    @classmethod
    def _has_usable_text(cls, extracted_text) -> bool:
        length = cls._text_length(extracted_text)
        return length > 0 and length >= MIN_ARTICLE_CHARS

    @classmethod
    def _best_of(cls, current, candidate):
        """Keep whichever extraction result has more text, so a failed fallback never
        replaces a short-but-real result with nothing."""
        return candidate if cls._text_length(candidate) > cls._text_length(current) else current

    @staticmethod
    def _trafilatura_fallback(soup) -> Union[List[str], None]:
        try:
            import trafilatura
            html = str(soup)
            with LXML_PARSE_LOCK:
                text = trafilatura.extract(html)
        except Exception as t_err:
            logger.warning(f"Trafilatura fallback failed: {t_err}")
            return None
        if not text:
            return None
        logger.info("Trafilatura extraction successful.")
        # Split into paragraphs to match the shape site extractors return.
        return text.split("\n\n")

    @staticmethod
    def _newspaper_fallback(url) -> Union[List[str], None]:
        try:
            article = Article(url)
            article.download()
            with LXML_PARSE_LOCK:  # SYS-52: newspaper parses with lxml
                article.parse()
        except Exception as n_err:
            logger.warning(f"Newspaper fallback failed: {n_err}")
            return None
        return article.text.split("\n\n") if article.text else None

    @abstractmethod
    def _get_reporter_from_text(self, soup) -> List[str]:
        pass

    @staticmethod
    def _looks_like_a_name(candidate: str) -> bool:
        """SRC-10 (#65): a reporter candidate that is purely digits or parses as a
        date is not a name -- it's a selector that landed on a timestamp or an id.
        A shared guard here catches this class of bug for every crawler's
        _get_reporter_from_text, not just the one instance already found."""
        if not candidate or not candidate.strip():
            return False
        stripped = candidate.strip()
        if re.match(r"^\d+$", stripped):
            return False
        # Date-shaped strings: "16/09/2026 17:54 WIB", "2026-09-16", "16.09.2026".
        if re.match(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", stripped):
            return False
        return True
