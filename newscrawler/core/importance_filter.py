import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from sentence_transformers import SentenceTransformer

from newscrawler.core import importance_probe
from newscrawler.core.importance_probe import PROBE_DIR, ImportanceProbe, ProbeArtifactError, embed_for_probe

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
# are NOT here. Galleries, video pages and calendar archives are a
# branch-level call (SRC-35/SRC-45), not this list's: IDXCHANNEL `foto` is
# finance posts with bodies and is kept there by exception, while its `video`
# is dropped. No `foto`/`video`/`galeri` category is denied here, so the rows
# those sections already produced keep their saved articles.
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
    # SYS-49 (#147, owner decision 2026-09-23): opinion / analysis / editorial
    # columns are soft -- they argue about an event, they are not one. This is
    # the enforcement point, not the probe: the four SINDONEWS `scope` Iran-war
    # analyses that split across tau are near-identical as text, so no
    # classifier separates them; the publisher's own section name does.
    # Every name below was sampled (4 live titles each, table on SYS-49) and
    # removed from category_vocabulary_not_denied.json in the same commit:
    #   CNBC/JPNN `opini`          -- "Ekonomi Pancasila dan Strategi Rantai Pasok Hijau"
    #   MEDIAINDONESIA `editorials`-- "Pastikan IKN bukan Proyek Mangkrak"
    #   MEDIAINDONESIA `kolom-pakar`-- "Aroma Politik dalam Putusan MK"
    #   MEDIAINDONESIA `surat-pembaca` -- "Kemacetan di Jalan Raya Lenteng Agung"
    #   SINDONEWS `scope`          -- "Standar Ganda Amerika, Kian Nyata Dukung Genosida di Gaza"
    # `analisis` is deliberately NOT here: a market-analysis desk reports as
    # often as it argues, and no sample was taken of one.
    "opini", "opinion", "editorial", "editorials", "kolom", "kolom-pakar",
    "surat-pembaca", "scope", "tajuk", "tajuk-rencana",
    # SRC-49 (#160): compound soft-vertical names the word-bounded stems cannot
    # reach, found by OPS-19's first-run crawl of the never-crawled sources.
    # These are the values already sitting in `sitemaps.category`, so the branch
    # fix alone would not deny them. All sampled:
    #   KONTAN `sportsetup` (27 rows, sportsetup.kontan.co.id) -- "Manchester
    #     United vs Manchester City: Rekor Head to Head", "Prediksi Borneo FC vs
    #     Persija", "Jadwal Timnas Bulu Tangkis di Asian Games 2026"
    #   DETIK `sportstyle` -- "Tennis Cup 2026", "Chair Pilates Bisa Jadi
    #     Tantangan Baru", "Ajak Main Gokart di Kelapa Gading"
    #   DETIK `korean-wave` -- "Teaser Comeback Kim Woo Bin di Drakor",
    #     "Lee Min Ho Saingan Berat Byun Yo Han di Bioskop"
    "sportsetup", "sportstyle",
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
    # SRC-49 (#160): DETIK stores the BRANCH key as the category, so its K-drama
    # desk lands as `pop/korean-wave` (100 rows). `is_offtopic_category` matches
    # the whole value, not the last segment, so the exact entry `korean-wave`
    # could not reach it and `korea` word-bounded stops at the "n". Word-bounded
    # `korean` matches at the `-`. This asymmetry is worth remembering: a name
    # added to SOFT_BRANCH_WORDS is NOT thereby denied at category level -- the
    # two vocabularies are separate, and a compound branch key needs both.
    "korean",
    # SYS-49: the same names word-bounded, so a host-qualified key
    # (`bali/opini`, SRC-41's shape) or a URL-shaped category is caught too.
    # Word-bounded on purpose: `scope` must never match `horoscope`, and
    # `opini` must not swallow an unrelated word that merely starts with it --
    # `opinion` is listed separately for the same reason (SYS-42's rule).
    "opini", "opinion", "editorial", "kolom", "tajuk", "scope", "surat-pembaca",
)

# SRC-50 (#162): soft leaves a source names after the SPECIFIC sport, meal or
# ritual, so no vocabulary word reaches them -- DETIK's `f1`, `raket`,
# `tempat-makan`, `hikmah/doa-dan-hadits`, and `relationship`, which holds its
# horoscopes. A vocabulary sweep cannot find a leaf that contains no vocabulary
# word, so these were decided the only complete way: 3 stored titles for EVERY
# leaf the source crawls (`sample_branch_titles.py --website DETIK --all-kept`,
# 2026-09-25: 242 listed, 173 kept, all 173 read; table on SRC-50).
#
# Rule: a leaf is listed here only when all 3 titles are soft. A mixed leaf stays
# crawled and the probe decides inside it (`living`, `properti/kepemilikan-rumah`,
# `sumut/budaya`, `hikmah/ziswaf`, `cerita-perjalanan`'s one news item notwithstanding
# -- its 3 were all travel). An empty leaf (`mobil`, `review`, `kebugaran`, `x/*`)
# has no titles, so it is not decided by name.
#
# ONE definition, used twice: the category gate denies these values for that
# source (DETIK stores the branch key as `sitemaps.category`, SRC-49's lesson),
# and `DetikCrawler.SOFT_BRANCH_DENY` is this same set, so the two cannot drift.
#
# SOURCE-SCOPED, exact-match. `category_gate(value, source)` denies a leaf only
# for the source that owns it. The first version was fleet-wide, and the live
# collision probe (scripts/experiments/probe_branch_category_mismatch.py) found
# KONTAN listing a `sehat` branch of its own -- empty, so unsampleable -- that a
# fleet-wide `sehat` would have denied by name alone. A stored-rows check cannot
# see a branch that has never been stored; the source scope makes the question
# moot. Also checked 2026-09-25: none of these is in NEWS_CATEGORIES, and none
# has a saved article or a gold-set row.
SOURCE_SOFT_LEAVES = {
    "DETIK": frozenset({
        # sport named by the sport -- F1 GP results, MotoGP standings, Asian
        # Games badminton; `basket` carries football (Van Dijk, Mbappe)
        "basket", "f1", "moto-gp", "raket",
        # horoscopes and love advice: "Ramalan Zodiak 25 September" x3,
        # "Zodiak Capricorn Kenapa Susah Dapat Jodoh?"
        "relationship", "ask-the-expert",
        # religion guides, stories and umrah-package adverts (`hikmah/ziswaf`,
        # 2 of 3 Kemenag policy, stays)
        "hikmah/dakwah", "hikmah/doa-dan-hadits", "hikmah/haji-dan-umrah", "hikmah/khazanah",
        "hikmah/kisah", "hikmah/muslimah", "hikmah/pesantren",
        # travel: "5 Destinasi Dekat Sydney", "Beach Club di Lantai 28",
        # "Menepi Sejenak di Bukit Pamoyanan"
        "cerita-perjalanan", "destination", "domestic-destination", "international-destination",
        "jogja/plesir",
        # food: "5 Coffee Shop di Senayan", "5 Resep MPASI 6 Bulan"
        "tempat-makan", "makanan-anak",
        # music / celebrity / pop culture: Grammy nominees, concert line-ups,
        # anime, film synopses and song lyrics filed under regional `budaya`
        "music", "pop/awards", "pop/culture", "pop/music", "pop/pensi", "pop/trending", "culture",
        "jabar/jabar-gaskeun", "jabar/budaya", "jateng/budaya", "jatim/budaya", "jogja/budaya",
        "kalimantan/budaya", "sulsel/budaya", "sumbagsel/budaya",
        # lifestyle, beauty, sex and self-care advice, health explainers
        "hijab", "wedding", "diet", "sexual-health", "sale-and-shop", "sehat",
        "bank-obat-dan-penyakit", "konsultasi", "true-story", "work-and-money",
        # celebrity houses, interior tips, property listings
        "properti/review-properti", "properti/arsitektur-dan-interior", "properti/tips-dan-panduan",
        "properti/list-properti",
        # hobby automotive and product reviews: "Modifikasi Grand Filano",
        # "Segini Harga Suzuki RGR 150 yang Dinaiki Duta Sheila On 7",
        # "Membedah Fitur Keamanan Daihatsu Rocky Hybrid"
        "modifikasi", "road-warriors", "editors-choice", "tips-and-tricks",
        # how-to, glossary and press-release columns: "Cara Menentukan Safety
        # Stock untuk Seller", "Apa itu EBITDA?", "Sangfor Partner Summit"
        "insight", "kamus", "story",
        # reader complaints and reader polls -- the `surat-pembaca`/opinion class
        # (SYS-49): "Koneksi Indosat Hifi Sering Mati", "Setuju atau Nggak?"
        "suara-pembaca", "prokontra",
        # Already denied at category level by the `tainment` stem, yet still
        # listed as a branch, so every row was fetched to be rejected (the
        # mismatch probe found it). Its titles agree: "Kisah Nanda dan Ninda,
        # Kembar ... Kuliah Kedokteran Bareng", "Mau Bikin Website dengan AI?"
        "edu/edutainment",
    }),
    # SRC-38 (#131, 2026-09-25): www.kompas.com's sections, listed for the first
    # time. All 32 kept leaves sampled (sample_branch_titles.py --website KOMPAS
    # --all-kept); these 11 were soft on all 3 titles. Kept as mixed or hard:
    # money, properti, global, edu, tren, cekfakta, lampung, riau,
    # sumatera-utara, sumatera-barat, sulawesi-selatan.
    "KOMPAS": frozenset({
        # sport named by the sport: "Hasil Bulu Tangkis Asian Games 2026"
        "badminton", "motogp",
        # home decor ("6 Elemen Esensial untuk Rumah Gaya Japandi"), exam question
        # banks ("50 Soal PTS IPA Kelas 7"), science curiosities rather than
        # developments ("Ikan Moonwalk", "Pohon Berjalan")
        "homey", "skola", "sains",
        # provincial SEO/service desks: "Tanggal 25 September Memperingati Hari
        # Apa?", KRL timetables, BMKG weather forecasts x3
        "jawa-barat", "jawa-tengah", "jawa-timur", "kalimantan-barat", "kalimantan-timur", "banten",
    }),
    # SRC-33 (#119, 2026-09-26): VIVA keyed properly for the first time (its 29
    # subdomains used to be keyed by URL). All 42 kept leaves sampled; these 10
    # were soft on all 3 titles. Kept: the news desks, `digital` (product news is
    # the probe's call, SRC-35), `indepth`, `ragam`, and 23 regional sites.
    "VIVA": frozenset({
        # lifestyle / celebrity / sport under a place or brand name: "4
        # Rekomendasi Kafe Ikonik di Jl Braga", "Taylor Swift Resmi Umumkan",
        # "Arsenal Nekat Goda Vinicius", "Apakah Ozempic Menyebabkan Diare?"
        "bandung", "jabar", "mindset", "ceritakita", "olret",
        # hobby automotive tips and gadget listicles
        "otomotif", "teknodaily",
        # sponsored/press-release items, reader complaints, humour
        "trending", "surat", "vbuzz",
        # its BRANCH was already dropped by the vocabulary word `gadget`, which the
        # category deny list does not carry -- so its 507 stored rows still went to
        # the probe (SRC-49's two-list gap; a fleet sweep found only this one plus
        # IDXCHANNEL `video`, which SRC-45 keeps on purpose)
        "gadget",
    }),
    # SRC-53 (#173): iNews TV's sections, stored before SRC-27 narrowed INEWS to
    # finance and renamed from their sitemap URLs. `inews-tv/talkshow` is TV
    # programme promos and debate-show clips, soft on every title sampled
    # 2026-09-26 ("Jangan Lewatkan Rakyat Bersuara Malam Ini: ... Live di iNews",
    # "Saksikan Malam Ini di Interupsi: ...", "Panas! Firdaus Oiwobo Ribut hingga
    # Nyaris Baku Hantam ..."): SRC-45's promo/video class and SYS-49's
    # argue-about-an-event class. Not denied: `inews-tv` (188 saved, hard news)
    # and `inews-tv/eksklusif`, which is mixed (promos and "Food Diary" next to
    # the Pati PBB protest and a malpractice victim's account), so the probe
    # decides. `inews-tv/religi` is already denied by the substring rule.
    "INEWS": frozenset({
        "inews-tv/talkshow",
    }),
}

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


def is_offtopic_category(category: Optional[str], source: Optional[str] = None) -> bool:
    """SYS-31: hard deny-list applied before the semantic score, on categories
    that are never news-worthy regardless of what the article text scores.

    SRC-50: `source` adds that source's own SOURCE_SOFT_LEAVES. Every caller
    that has the row's source passes it, so the live filter and every script
    decide alike (a test checks the call sites)."""
    normalized = _normalize(category)
    if not normalized:
        return False
    if normalized in OFFTOPIC_CATEGORIES_EXACT:
        return True
    if source and normalized in SOURCE_SOFT_LEAVES.get(source.strip().upper(), ()):
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


def category_gate(category: Optional[str], source: Optional[str] = None) -> Optional[str]:
    """The ONE category decision every caller uses (live filter, backfill and
    re-queue scripts): "deny" for a soft vertical, "allow" for a news desk,
    None for a mixed or unknown bucket that the score has to arbitrate. Deny
    is checked first so a URL-shaped or hyphenated value that happens to
    contain a soft stem can never be allowed by accident. `source` scopes the
    per-source soft leaves (SRC-50)."""
    if is_offtopic_category(category, source):
        return "deny"
    if is_news_category(category):
        return "allow"
    return None


# The two vocabularies must never overlap, or which one wins becomes a matter
# of evaluation order instead of policy. Checked once at import.
_overlap = sorted(name for name in NEWS_CATEGORIES if is_offtopic_category(name))
if _overlap:
    raise RuntimeError(f"NEWS_CATEGORIES entries also matched by the deny-list: {_overlap}")


# ── SYS-37 (#121): the probe decides ─────────────────────────────────────────
# The cosine-vs-INTERESTS score (threshold 0.35 + the SYS-31 margin) is gone.
# World oil prices scored 0.254, Boeing shares 0.203 (SYS-35), a poem and a
# vasectomy story cleared it (SYS-34): the embedding was fine, the comparison
# against short phrases was not. What decides now is `ImportanceProbe`
# (newscrawler/core/importance_probe.py): two logistic-regression heads over
# the `multilingual-e5-large` embedding, trained on the SYS-36 gold set by
# scripts/train_importance_probe.py -- P(soft) is the news-worthy gate, the
# topic head gives `articles.topic`. The committed artifact's sidecar names
# the encoder, the threshold and the metrics it was accepted on; the filter
# loads exactly that encoder. A missing or mismatched artifact raises
# ProbeArtifactError at construction -- never a silent accept-all/reject-all.
#
# SYS-45 (#140, owner 2026-09-21): a news desk (`allow`) no longer means
# "never reject" -- it means the *score* cannot reject, the probe can.
# `deny` still rejects before anything is embedded.
UNCERTAIN_BAND = importance_probe.UNCERTAIN_BAND


@dataclass(frozen=True)
class FilterDecision:
    """What `SemanticImportanceFilter.classify` decided and why.

    gate: "allow" (news desk -- the probe still decides, SYS-45), "deny" (soft
      category, rejected before the probe), "score" (mixed bucket, the probe
      decided) or "empty" (nothing to score).
    score_passed: the probe's own verdict (P(soft) < threshold); None when it
      never ran. For an "allow" row this IS the decision; the per-run stat
      reports probe rejects per news category from it.
    topic / topic_confidence: the topic head's best news class and its
      probability among the news classes -- persisted to articles.topic /
      topic_confidence (SYS-37 fix 3). Set even for a rejected row.
    p_soft: the gate probability, for the uncertain-band telemetry.
    """
    is_important: bool
    gate: str
    score_passed: Optional[bool] = None
    topic: Optional[str] = None
    topic_confidence: Optional[float] = None
    p_soft: Optional[float] = None

    @property
    def in_uncertain_band(self) -> bool:
        return self.p_soft is not None and UNCERTAIN_BAND[0] <= self.p_soft <= UNCERTAIN_BAND[1]


class SemanticImportanceFilter:
    def __init__(self, probe: Optional[ImportanceProbe] = None, probe_dir: str = PROBE_DIR,
                 soft_threshold: Optional[float] = None, model: Optional[SentenceTransformer] = None):
        """Load the committed probe and the encoder its sidecar names.

        probe / model: injected for tests; production passes nothing and gets
            the artifact in PROBE_DIR plus a fresh SentenceTransformer.
        soft_threshold: override the sidecar's threshold (constants.SOFT_THRESHOLD
            from the env; None = the trainer's CV choice)."""
        self.probe = probe or ImportanceProbe.load(probe_dir, soft_threshold=soft_threshold)
        self.model_name = self.probe.encoder_name
        if not self.model_name:
            raise ProbeArtifactError("probe sidecar names no encoder")
        logger.info(f"Loading Semantic Filter encoder: {self.model_name}...")
        self.model = model if model is not None else SentenceTransformer(self.model_name)
        dim = self.model.get_sentence_embedding_dimension()
        if dim != self.probe.dim:
            raise ProbeArtifactError(f"{self.model_name} embeds to {dim} dims, the probe expects {self.probe.dim}")
        sidecar = self.probe.sidecar
        logger.info(
            f"Initialized Semantic Filter: probe trained {sidecar.get('trained_at', '?')} on "
            f"{sidecar.get('n_train', '?')} gold rows, soft_threshold={self.probe.soft_threshold:.2f}, "
            f"test recall_finance={sidecar.get('metrics_test', {}).get('recall_finance', float('nan')):.3f} "
            f"precision_mixed={sidecar.get('metrics_test', {}).get('precision_mixed', float('nan')):.3f}"
        )

    def is_important(self, text: str, category: Optional[str] = None, source: Optional[str] = None) -> bool:
        """Thin wrapper: news-worthy or not."""
        return self.classify(text, category, source).is_important

    def classify(self, text: str, category: Optional[str] = None, source: Optional[str] = None) -> FilterDecision:
        """One article. Thin wrapper over classify_batch."""
        return self.classify_batch([text], [category], [source])[0]

    def classify_batch(self, texts: Sequence[str], categories: Sequence[Optional[str]],
                       sources: Optional[Sequence[Optional[str]]] = None) -> List[FilterDecision]:
        """THE decision function -- the live filter, backfill_sitemap_crawl_status.py,
        the topic backfill and SYS-38's re-queue all go through here, so "same
        decision as the live filter" is true by construction. Category gate
        first: `deny` rejects without embedding; `allow` and mixed buckets are
        embedded once as a batch and decided by the probe.

        CONTRACT (DBT-36 #152): exactly one FilterDecision per input text, in
        input order. Every caller pairs the result with its inputs positionally
        by `zip`, and two of them write to or delete from production, so a
        result one element short would silently attribute every verdict after
        the gap to the wrong article. A violation raises here instead."""
        if len(texts) != len(categories):
            raise ValueError("texts and categories must have the same length")
        if sources is None:
            sources = [None] * len(texts)
        elif len(sources) != len(texts):
            raise ValueError("texts and sources must have the same length")
        decisions: List[Optional[FilterDecision]] = [None] * len(texts)
        to_score = []
        for i, (text, category, source) in enumerate(zip(texts, categories, sources)):
            if not text or not text.strip():
                decisions[i] = FilterDecision(is_important=False, gate="empty")
                continue
            gate = category_gate(category, source)
            if gate == "deny":
                decisions[i] = FilterDecision(is_important=False, gate="deny")
                continue
            to_score.append((i, text, gate))
        if to_score:
            embeddings = embed_for_probe(self.model, [t for _, t, _ in to_score], model_name=self.model_name)
            predictions = list(self.probe.predict(embeddings))
            # A short `predict` must fail at its source, not propagate through
            # `zip` as a truncation nobody can see downstream.
            if len(predictions) != len(to_score):
                raise ProbeArtifactError(
                    f"probe.predict returned {len(predictions)} rows for {len(to_score)} embedded text(s)")
            for (i, _, gate), (is_news, topic, confidence, p_soft) in zip(to_score, predictions):
                decisions[i] = FilterDecision(
                    is_important=is_news, gate=gate or "score", score_passed=is_news,
                    topic=topic, topic_confidence=confidence, p_soft=p_soft,
                )
        # Backstop: the check above already guarantees every scored slot is
        # filled, so this can only fire if the assignment logic itself grows a
        # hole. It replaces `[d for d in decisions if d is not None]`, which
        # turned exactly that bug into a silently shortened, misaligned list.
        undecided = [i for i, d in enumerate(decisions) if d is None]
        if undecided:
            raise ProbeArtifactError(
                f"classify_batch left {len(undecided)} of {len(texts)} text(s) undecided "
                f"(first at index {undecided[0]}) -- refusing to return a short, misaligned list")
        return list(decisions)
