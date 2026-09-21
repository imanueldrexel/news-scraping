import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from sentence_transformers import SentenceTransformer, util

# Configure logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-31 (#86): category values that are never news-worthy on any outlet
# observed in production, applied before the semantic score. Lifestyle/
# entertainment/sports/religion-guide/travel verticals and GRIDID's whole
# magazine network score inside the model's noise band ([0.35, 0.45) against
# short INTERESTS phrases) just as often as real economy news -- "Ria Ricis
# Nangis Lihat Sapi Kurbannya Disembelih" scores 0.421 vs `Rupiah`, above the
# corpus median -- so no threshold on the cosine score alone can separate
# them; the category is a free, reliable signal.
#
# Scope (2026-09-20, owner decision, SYS-36 #120 / SRC-39 #133): the product
# keeps everything *news-worthy*, not only finance. So this list is the soft
# verticals of the rubric -- recipes, prayer guides, horoscopes, gossip,
# listicles, tips, fiction, sports, advertorials -- and nothing that is a news
# desk. `kriminal` (crime is news) and `edukasi` (education policy is news;
# sampled 2026-09-20 on SINDONEWS/OKEZONE/VIVA: Kemendikdasmen rules, PDSS
# schools, a new UI rector) came off it under that scope (SYS-35 #118,
# SYS-34 #115).
#
# NOTE (2026-09-20, pre-cleanup verification for SYS-31's data-deletion step):
# "otomotif" was removed from both sets below after sampling actual saved
# titles under it on WARTAEKONOMI and SINDONEWS -- both were real auto-market
# business coverage (EV subsidies, fiscal risk, car sales/market-share
# figures), not lifestyle car reviews. A bare "otomotif" category label does
# not reliably mean off-topic on this corpus; GRIDID's dedicated car-hobbyist
# magazine brands (Gridoto, Motorplus, Otomotifnet) are unambiguous and stay.
#
# SYS-34 (#115): this list is allow-by-default and was first built from the
# vocabulary in the DB on 2026-09-19; IDNTIMES's `life`/`hype`/`korea`/
# `fiction`/`men`/`food` leaked poems and celebrity weddings straight through.
# Every entry added on 2026-09-20 was sampled (3-4 random titles) before it
# went in -- OKEZONE `muslim` (haji security, Wamenhaj) and `ototekno` (Meta
# subscriptions, an AI presenter) looked soft by name and are news, so they
# are NOT here. `foto`/`video` on IDXCHANNEL are finance posts with bodies;
# gallery-only branches are SRC-35's branch-level call, not this list's.
OFFTOPIC_CATEGORIES_EXACT = {
    "hiburan", "fashion", "lifestyle", "olahraga", "bola", "sport", "sports",
    "kuliner", "sajian", "travel", "wisata", "destinasi", "piknik",
    "religi", "kalam", "ramadan", "forum-mahasiswa",
    "entertainment", "gaya-hidup", "idxtainment", "ecotainment",
    "entertainment_life_style", "travelista", "sepak-bola", "sepakbola", "jelita",
    # SYS-34: IDNTIMES's vocabulary (poems, K-drama recaps, OOTD, kuliner).
    "life", "hype", "korea", "fiction", "men", "food",
    # 2026-09-20, sampled: OKEZONE `celebrity` (sinetron synopses, MNCTV
    # roadshows) / `women` (rest-area tips, "5 Wisata Prancis"); KUMPARAN
    # `woman`/`mom` (self-help, parenting tips); TRIBUN `seleb` (pregnancy
    # announcements), `musik` (lyrics and guitar chords), `superskor` (Persib,
    # Barcelona); VIVA `showbiz` (914 rows -- "Alyssa Daguise Ngaku Kena
    # Prank"), `siaran-pers` (bank press releases; the rubric drops reprints);
    # JPNN `donwori` (a relationship-confession column: "Istri Bawa Pria Lain
    # ke Ruang Tengah", 24 saved), `advetorial` (advertorials), `piala-eropa`;
    # MEDIAINDONESIA `sajak-kofe` (poetry), `piala-dunia-2026`; KUMPARAN
    # `bolanita`; VIVA `vstory`/`blog` (user-submitted), `english`.
    "celebrity", "selebriti", "seleb", "showbiz", "women", "woman", "mom",
    "musik", "superskor", "siaran-pers", "donwori", "advetorial", "advertorial",
    "sajak-kofe", "bolanita", "vstory", "blog", "english", "english_edition",
    "piala-eropa", "piala-dunia-2026", "horoskop", "zodiak", "resep", "games",
    "quiz", "kpop", "film", "movie", "beauty", "kecantikan",
    # GRIDID: every category the source has ever saved under is a lifestyle/
    # hobby magazine brand (Grid Network), none news.
    "gridid", "intisari", "fotokita", "idea", "nationalgeographic", "nakita",
    "nova", "infokomputer", "gridoto", "otomotifnet", "hai", "motorplus",
    "gridhealth", "nextren", "juara", "cewekbanget", "bolasport", "stylo",
    "superball", "bobo", "otoseken",
}
# Substring match for category values that are not clean labels -- e.g. a
# raw per-region sitemap URL stored as `category` (JPNN before SRC-41, VIVA's
# subdomains until SRC-33: "https://wisata.viva.co.id/sitemap/news/...").
# Most of these are checked as plain substrings; a few are checked with a
# word boundary instead (see is_offtopic_category) because "transportasi" --
# Indonesian for "transportation", nothing to do with sports -- contains
# "sport" by pure coincidence (tran-SPORT-asi) and was a real false positive
# on WARTAEKONOMI caught by sampling actual titles before the SYS-31 cleanup
# delete ran; "wisata" is word-bounded for the same reason ("pariwisata" is
# the tourism industry).
#
# SYS-42 (#137): a substring stem is a collision with the next source's
# vocabulary waiting to happen -- `celeb` (added by SYS-34) matched INEWS's
# Sulawesi desk `celebes` and would have permanently rejected 200 regional
# hard-news rows on the next INEWS run. A stem short enough to be a prefix
# of a real word goes on the word-bounded list; a substring stem must be a
# whole word itself (`celebrity`, `olahraga`, `showbiz`). Every stem on both
# lists is checked against the live not-denied vocabulary in
# tests/fixtures/category_vocabulary_not_denied.json before it ships.
OFFTOPIC_CATEGORY_KEYWORDS_SUBSTRING = (
    "olahraga", "lifestyle", "hiburan", "kuliner",
    "travel", "religi", "destinasi", "tainment",
    # SYS-34 (VIVA evidence): the Indonesian/English stems the exact list
    # already has, so URL-shaped categories are caught too.
    "showbiz", "seleb", "celebrity", "zodiak", "horoskop", "resep",
    "fiction", "renungan", "tafsir", "advetorial", "advertorial",
)
OFFTOPIC_CATEGORY_KEYWORDS_WORD = (
    "sport", "wisata", "bola", "food", "piala", "gossip", "gosip",
    # SYS-42: `celeb`/`celebs` as a word only -- never the prefix of `celebes`.
    "celeb",
)

# Short topic anchors for verticals that keep landing in the cosine noise band
# against INTERESTS even though they are not finance. Used as a contrastive
# check (SemanticImportanceFilter.margin): an article must score higher against
# INTERESTS than against these, not merely clear the raw threshold. This is the
# fallback for articles whose sitemap.category is missing, blank, or not (yet)
# covered by the deny-list above. No "Otomotif" entry, for the same reason
# it isn't a category keyword -- real auto-market business content would
# score close to it too.
#
# Deliberately NOT re-tuned for the news-worthy scope ("Kriminal dan
# Kecelakaan" / "Politik dan Pemilu" are news now): the whole cosine-vs-phrase
# stage is replaced by SYS-37 (#121), and three tuning passes on it have each
# failed the next audit. Until then it only ever arbitrates mixed buckets,
# never a category in NEWS_CATEGORIES.
OFFTOPIC_INTERESTS = [
    "Hiburan dan Gosip Selebriti", "Gaya Hidup dan Fashion", "Kuliner dan Resep Masakan",
    "Olahraga dan Sepak Bola", "Wisata dan Travel", "Agama dan Religi",
    "Kriminal dan Kecelakaan", "Politik dan Pemilu",
]

# SYS-35 (#118): the category gate was asymmetric by accident -- a category
# known to be soft won before the score, but a category known to be news
# still had to survive a score that rejects world oil prices at 0.254 and
# Boeing shares at 0.203. 30-55% of every outlet's dedicated finance section
# was permanently `rejected_filter` (LIPUTAN6 `bisnis` 55.5%, SUARA 47%,
# MERDEKA `uang` 44%). These sets make the gate symmetric: a category the
# publisher itself files as news short-circuits to "news" before the score,
# and the score only ever arbitrates the genuinely mixed buckets.
#
# Exact match only, on the publisher's own section name. A bucket called
# `news`/`berita`/`news-sitemap`/`sitemap` is NOT here -- owner decision,
# 2026-09-20 (recorded on SYS-35 #118): on KUMPARAN `news` was 1 of 4 hard
# news in a random sample (photo gallery, a how-to and an opinion piece
# beside it), on VIVA `news-sitemap` 0 of 4 -- those are the mixed buckets
# the score (and SYS-37's probe) exists for, and SYS-37's precision gate is
# measured on exactly them. Names that read as news but sampled mixed
# stay out too: `pendidikan` (JPNN: policy; MEDIAINDONESIA: "17 Pakaian Adat
# Sumatera Barat"), `syariah` (Kemenag haji policy next to Idul Adha greeting
# listicles), `humaniora`, `research`, `mymoney` (personal-finance tips),
# `csr` (press releases), `kesehatan` (Ebola outbreak next to "Kenali
# Gejala"), `otomotif` (business on WARTAEKONOMI, hobby on VIVA/KUMPARAN).
# Every name below was sampled on 2026-09-20 or is that name's plain
# translation; a widened crawler's new vocabulary is caught by the
# never-seen-category WARNING in the service (SYS-34 fix c), not assumed.
NEWS_CATEGORIES_FINANCE = {
    # Dedicated finance/economy/market desks -- the SYS-35 re-queue population.
    "bisnis", "ekonomi", "uang", "finance", "business", "ekbis", "saham",
    "keuangan", "makro", "bursa", "finansial", "perbankan", "market",
    "market-news", "banking", "economics", "economia", "economy", "ekonomi-bisnis",
    "money", "moneter", "fiskal", "emiten", "investasi", "komoditas", "kurs",
    "crypto", "kripto", "industri", "energi", "asuransi", "multifinance",
    "agribisnis", "pajak", "properti", "infrastruktur", "digital_economy",
    "green_economy", "dana_pensiun", "perencanaan_keuangan", "riil",
    "new-economy", "umkm-bisa", "umkm", "the-founder", "mikro", "makroekonomi",
}
NEWS_CATEGORIES_HARD = {
    # National / political / legal / regional / international desks.
    "nasional", "national", "politik", "politics", "politik-dan-hukum",
    "hukum", "hukum-kriminal", "kriminal", "crime", "law",
    "internasional", "international", "dunia", "global", "world",
    "daerah", "regional", "nusantara", "megapolitan", "metropolitan", "metro",
    "pemilu", "pilkada", "militer", "peristiwa", "breaking-news",
    "abc-indonesia",
}
NEWS_CATEGORIES = NEWS_CATEGORIES_FINANCE | NEWS_CATEGORIES_HARD


def _normalize(category: Optional[str]) -> str:
    return (category or "").strip().lower()


def is_offtopic_category(category: Optional[str]) -> bool:
    """SYS-31: hard deny-list applied before the semantic score, on categories
    that are never news-worthy regardless of what the article text scores."""
    normalized = _normalize(category)
    if not normalized:
        return False
    if normalized in OFFTOPIC_CATEGORIES_EXACT:
        return True
    if any(keyword in normalized for keyword in OFFTOPIC_CATEGORY_KEYWORDS_SUBSTRING):
        return True
    # Plain \b treats "_" as a word character, so it would not see a boundary
    # in "post_sport" -- category/URL slugs use "_"/"-"/"." as separators just
    # as often as they use letters, so the boundary is "not alphanumeric".
    return any(
        re.search(rf"(?:^|[^a-z0-9]){keyword}s?(?:[^a-z0-9]|$)", normalized)
        for keyword in OFFTOPIC_CATEGORY_KEYWORDS_WORD
    )


def _section_name(category: Optional[str]) -> str:
    """The publisher's section name: the whole value, or for a host-qualified
    key like JPNN's `bali/politik` (SRC-41) or INEWS's `finance/keuangan`
    (SRC-34) its last segment. A URL never gets here as a name -- it has no
    bare segment the allow-set could match, so it stays a mixed bucket."""
    normalized = _normalize(category)
    if normalized.startswith("http"):
        return ""
    return normalized.rsplit("/", 1)[-1]


def is_news_category(category: Optional[str]) -> bool:
    """SYS-35: the publisher files this section as news (finance or hard
    news) -- exact match on the section name, never a substring."""
    normalized = _normalize(category)
    return normalized in NEWS_CATEGORIES or _section_name(category) in NEWS_CATEGORIES


def is_finance_category(category: Optional[str]) -> bool:
    """SYS-35: the dedicated finance/economy sections -- the population whose
    `rejected_filter` rows the SYS-35 re-queue resets."""
    normalized = _normalize(category)
    return normalized in NEWS_CATEGORIES_FINANCE or _section_name(category) in NEWS_CATEGORIES_FINANCE


def category_gate(category: Optional[str]) -> Optional[str]:
    """The ONE category decision every caller uses (live filter, backfill and
    re-queue scripts): "deny" for a soft vertical, "allow" for a news desk,
    None for a mixed or unknown bucket that the score has to arbitrate. Deny
    is checked first so a URL-shaped or hyphenated value that happens to
    contain a soft stem can never be allowed by accident."""
    if is_offtopic_category(category):
        return "deny"
    if is_news_category(category):
        return "allow"
    return None


# The two vocabularies must never overlap, or which one wins becomes a matter
# of evaluation order instead of policy. Checked once at import.
_overlap = sorted(name for name in NEWS_CATEGORIES if is_offtopic_category(name))
if _overlap:
    raise RuntimeError(f"NEWS_CATEGORIES entries also matched by the deny-list: {_overlap}")


@dataclass(frozen=True)
class FilterDecision:
    """What `SemanticImportanceFilter.classify` decided and why.

    gate: "allow" (news category, saved regardless of score), "deny" (soft
      category, rejected regardless of score), "score" (mixed bucket, the
      score decided), or "empty" (nothing to score).
    score_passed: what the semantic score alone would have said -- computed
      for allowed categories too, so the per-run pass-rate stat (SYS-35 fix 4)
      can report the score's recall on categories known to be news. None when
      the score never ran.
    """
    is_important: bool
    gate: str
    score_passed: Optional[bool] = None
    max_score: Optional[float] = None
    max_offtopic: Optional[float] = None


class SemanticImportanceFilter:
    def __init__(self, interests: List[str], threshold: float = 0.35, model_name: str = 'all-MiniLM-L6-v2',
                 offtopic_interests: Optional[List[str]] = None, margin: float = 0.035):
        """
        Initialize the Semantic Importance Filter.

        Args:
            interests: List of strings describing the user's interests (e.g. "Artificial Intelligence", "Stock Market").
            threshold: Cosine similarity threshold (0 to 1). Articles above this are "important".
            model_name: Sentence Transformer model name.
            offtopic_interests: SYS-31 -- reference topics an article must score
                below (relative to `margin`) its best `interests` score, even if
                it clears `threshold`. Raw cosine similarity against short
                INTERESTS phrases alone does not separate finance from
                lifestyle/entertainment content in the noise band just above
                `threshold`; scoring against a contrasting off-topic set catches
                what the category deny-list (`is_offtopic_category`) misses.
            margin: how much higher the best INTERESTS score must be than the
                best off-topic score for an article to pass.
        """
        logger.info(f"Loading Semantic Filter Model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.interests = interests
        self.threshold = threshold
        self.margin = margin

        # Pre-encode interests for speed
        self.interest_embeddings = self.model.encode(self.interests, convert_to_tensor=True)

        self.offtopic_interests = offtopic_interests or []
        self.offtopic_embeddings = (
            self.model.encode(self.offtopic_interests, convert_to_tensor=True)
            if self.offtopic_interests else None
        )
        logger.info(f"Initialized Semantic Filter with interests: {self.interests}")

    def is_important(self, text: str, category: Optional[str] = None) -> bool:
        """
        Check if the text is news-worthy: a news category is, a soft category
        is not, and anything else is decided by semantic similarity to the
        interests (SYS-31 margin included). Thin wrapper over `classify`.
        """
        return self.classify(text, category).is_important

    def classify(self, text: str, category: Optional[str] = None) -> FilterDecision:
        """The one decision function. Category gate first (SYS-31 deny,
        SYS-35 allow), then the score -- which also runs for an allowed
        category so its recall on known-news sections is measurable, but
        never for a denied one (nothing to learn, and the model is the
        expensive step)."""
        if not text:
            return FilterDecision(is_important=False, gate="empty")

        gate = category_gate(category)
        if gate == "deny":
            return FilterDecision(is_important=False, gate="deny")

        score_passed, max_score, max_offtopic = self._score(text)
        if gate == "allow":
            return FilterDecision(is_important=True, gate="allow", score_passed=score_passed,
                                  max_score=max_score, max_offtopic=max_offtopic)
        return FilterDecision(is_important=score_passed, gate="score", score_passed=score_passed,
                              max_score=max_score, max_offtopic=max_offtopic)

    def _score(self, text: str):
        """(passed, max_interest_score, max_offtopic_score) -- the SYS-31
        threshold + margin decision, unchanged."""
        # Truncate text to first 200 words for speed and relevance (intros usually contain the topic)
        text_snippet = " ".join(text.split()[:200])

        # Encode the article text
        article_embedding = self.model.encode(text_snippet, convert_to_tensor=True)

        # Calculate cosine similarities
        cosine_scores = util.cos_sim(article_embedding, self.interest_embeddings)

        # Find the max similarity score
        max_score = float(cosine_scores.max())
        max_offtopic = None

        if max_score < self.threshold:
            return False, max_score, max_offtopic

        if self.offtopic_embeddings is not None:
            offtopic_scores = util.cos_sim(article_embedding, self.offtopic_embeddings)
            max_offtopic = float(offtopic_scores.max())
            if max_offtopic + self.margin >= max_score:
                logger.debug(
                    f"Article scored {max_score:.3f} vs interests but {max_offtopic:.3f} "
                    f"vs off-topic anchors (margin {self.margin}) -- rejecting"
                )
                return False, max_score, max_offtopic

        logger.debug(f"Article matched with score {max_score:.3f}")
        return True, max_score, max_offtopic
