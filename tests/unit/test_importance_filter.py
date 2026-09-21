"""SYS-31 (#86): the category deny-list must reject known off-topic categories
without loading the embedding model, and the off-topic-anchor margin must be
wired into SemanticImportanceFilter's constructor/is_important signature.

SYS-35 (#118): the category gate is symmetric -- a section the publisher files
as news (`bisnis`, `nasional`, ...) is saved before the score runs, so the
score's 30-55% recall loss on dedicated finance sections can no longer turn
into a permanent `rejected_filter`. `kriminal` and `edukasi` are news under the
news-worthy scope and left the deny-list.

SYS-34 (#115): the deny-list knows the vocabulary that leaked poems, K-drama
recaps and OOTD listicles from IDNTIMES (`life`/`hype`/`korea`/`fiction`/
`men`/`food`) plus the soft verticals sampled across every source in the DB on
2026-09-20, and the SYS-31 margin is measured against those titles too.
"""
import unittest
from unittest.mock import MagicMock

from newscrawler.core.importance_filter import (
    FilterDecision,
    NEWS_CATEGORIES,
    NEWS_CATEGORIES_FINANCE,
    NEWS_CATEGORIES_HARD,
    OFFTOPIC_CATEGORIES_EXACT,
    OFFTOPIC_INTERESTS,
    SemanticImportanceFilter,
    category_gate,
    is_finance_category,
    is_news_category,
    is_offtopic_category,
)


class TestIsOffTopicCategory(unittest.TestCase):
    def test_none_and_empty_are_not_offtopic(self):
        self.assertFalse(is_offtopic_category(None))
        self.assertFalse(is_offtopic_category(""))

    def test_known_offtopic_categories(self):
        for cat in ("hiburan", "fashion", "lifestyle", "Sajian", "Nakita", "olahraga", "religi"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_case_insensitive(self):
        self.assertTrue(is_offtopic_category("HIBURAN"))
        self.assertTrue(is_offtopic_category("GridID"))

    def test_finance_categories_are_not_offtopic(self):
        for cat in ("ekonomi", "bisnis", "market-news", "banking", "finansial", "syariah"):
            self.assertFalse(is_offtopic_category(cat), f"{cat!r} should not be off-topic")

    def test_url_shaped_jpnn_category_matched_by_keyword(self):
        self.assertTrue(is_offtopic_category("https://bali.jpnn.com/sitemap_post_olahraga.xml"))
        self.assertTrue(is_offtopic_category("https://jogja.jpnn.com/sitemap_post_lifestyle.xml"))

    def test_ambiguous_regional_category_not_denied(self):
        self.assertFalse(is_offtopic_category("daerah"))
        self.assertFalse(is_offtopic_category("nasional"))

    def test_otomotif_is_not_denied(self):
        """2026-09-20, found while verifying the SYS-31 cleanup before it ran:
        sampled real saved titles under "otomotif" on WARTAEKONOMI and
        SINDONEWS -- both were auto-market business coverage (EV subsidies,
        car sales/market-share figures), not lifestyle reviews. A bare
        "otomotif" category is not a reliable off-topic signal on this corpus."""
        self.assertFalse(is_offtopic_category("otomotif"))
        self.assertFalse(is_offtopic_category("Otomotif"))

    def test_gridid_automotive_magazine_brands_still_denied(self):
        for cat in ("Gridoto", "Motorplus", "Otomotifnet", "SuperBall", "Bobo", "Otoseken"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should still be off-topic")

    def test_transportasi_is_not_a_false_positive_via_the_sport_substring(self):
        """"transportasi" (Indonesian for "transportation") contains "sport"
        purely by coincidence (tran-SPORT-asi) -- a plain substring check on
        the "sport" keyword flagged real WARTAEKONOMI logistics/infrastructure
        coverage as off-topic. Must not be denied."""
        self.assertFalse(is_offtopic_category("transportasi"))

    def test_pariwisata_is_not_a_false_positive_via_the_wisata_substring(self):
        # Tourism *industry* coverage; "wisata" is word-bounded for the same
        # reason "sport" is.
        self.assertFalse(is_offtopic_category("pariwisata"))
        self.assertTrue(is_offtopic_category("wisata"))
        self.assertTrue(is_offtopic_category("https://wisata.viva.co.id/sitemap/news/news-sitemap.xml"))

    def test_sport_keyword_still_matches_real_sport_categories(self):
        self.assertTrue(is_offtopic_category("bola-sports"))
        self.assertTrue(is_offtopic_category("https://bali.jpnn.com/sitemap_post_sport.xml"))
        self.assertTrue(is_offtopic_category("sport"))
        self.assertTrue(is_offtopic_category("bali/sport"))
        self.assertTrue(is_offtopic_category("sepakbola"))

    def test_celebes_is_not_a_false_positive_via_the_celeb_substring(self):
        """SYS-42 (#137): INEWS's `celebes` (celebes.inews.id, the Sulawesi
        regional desk -- 200 pending hard-news rows on 2026-09-21) contains
        "celeb" the way "transportasi" contains "sport". A substring stem
        denied it before the score; `celeb` is word-bounded now."""
        self.assertFalse(is_offtopic_category("celebes"))
        self.assertFalse(is_offtopic_category("Celebes"))
        self.assertFalse(is_offtopic_category("https://celebes.inews.id/sitemap.xml"))
        self.assertIsNone(category_gate("celebes"))

    def test_celeb_still_matches_real_celebrity_categories(self):
        for cat in ("celebrity", "Celebrity", "celeb", "celebs", "https://celebrity.okezone.com/sitemap.xml",
                    "https://www.example.com/celeb/sitemap.xml", "seleb", "KlikSeleb", "selebriti"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_no_deny_stem_collides_with_the_live_not_denied_vocabulary(self):
        """SYS-42 (#137): the inverse of SYS-34's title sampling. Every live
        (source, category) the gate did not deny on 2026-09-21 is in the
        fixture; a new stem on either keyword list that catches one of them
        fails here instead of permanently rejecting a real desk on the next
        run. To deny one of these on purpose, remove it from the fixture in
        the same commit, with the 3-title sample on the ticket."""
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "category_vocabulary_not_denied.json")
        with open(path, encoding="utf-8") as f:
            pairs = json.load(f)["pairs"]
        self.assertGreater(len(pairs), 300, "fixture looks truncated")
        collisions = [
            f"{p['source']}/{p['category']}" for p in pairs if is_offtopic_category(p["category"])
        ]
        self.assertEqual(
            collisions, [],
            "deny-list stems now catch live categories that were not denied on 2026-09-21 -- sample their "
            "titles before denying them (SRC-39), then update the fixture in the same commit",
        )
        # The two known collisions are in the fixture and so covered above;
        # pin them by name too, so the message says what broke.
        names = {p["category"].lower() for p in pairs}
        self.assertIn("celebes", names)
        self.assertIn("transportasi", names)


class TestNewsWorthyScopeDenyList(unittest.TestCase):
    """SYS-34 (#115) + SYS-35 (#118): what left the list and what joined it."""

    def test_kriminal_is_news_and_no_longer_denied(self):
        self.assertFalse(is_offtopic_category("kriminal"))
        self.assertFalse(is_offtopic_category("https://bali.jpnn.com/sitemap_post_kriminal.xml"))
        self.assertFalse(is_offtopic_category("bali/kriminal"))

    def test_edukasi_is_news_and_no_longer_denied(self):
        # Sampled 2026-09-20: Kemendikdasmen rules, PDSS schools, a new UI rector.
        self.assertFalse(is_offtopic_category("edukasi"))

    def test_idntimes_vocabulary_is_denied(self):
        # The 29 leaked rows: poems, K-drama recaps, OOTD, celebrity weddings, kuliner.
        for cat in ("life", "hype", "korea", "fiction", "men", "food"):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_health_and_science_are_not_denied(self):
        # Withdrawn under the news-worthy rubric: outbreaks and science
        # developments are news; soft content inside them is SYS-37's job.
        self.assertFalse(is_offtopic_category("health"))
        self.assertFalse(is_offtopic_category("science"))
        self.assertFalse(is_offtopic_category("kesehatan"))

    def test_sampled_soft_verticals_across_sources_are_denied(self):
        for cat in (
            "celebrity", "women", "woman", "mom", "seleb", "showbiz", "musik",
            "superskor", "siaran-pers", "donwori", "advetorial", "sajak-kofe",
            "bolanita", "vstory", "blog", "english", "english_edition",
            "piala-eropa", "piala-dunia-2026", "food-travel", "renungan-ramadan",
            "tafsir-al-mishbah",
        ):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_sampled_news_that_looks_soft_by_name_is_not_denied(self):
        # OKEZONE `muslim` (haji security, Wamenhaj), `ototekno` (Meta
        # subscriptions, AI presenter), IDXCHANNEL `foto`/`video` (finance
        # posts with bodies), JPNN `pendidikan` -- names are not evidence.
        for cat in ("muslim", "ototekno", "foto", "video", "pendidikan", "tribunners", "jurnal-kopi"):
            self.assertFalse(is_offtopic_category(cat), f"{cat!r} should not be off-topic")

    def test_men_is_exact_only_so_menteri_and_men_prefixes_are_untouched(self):
        self.assertFalse(is_offtopic_category("menteri"))
        self.assertFalse(is_offtopic_category("mengenal-saham"))


class TestNewsCategoryAllowSet(unittest.TestCase):
    """SYS-35 (#118): the symmetric half of the gate."""

    def test_finance_sections_are_news(self):
        for cat in ("bisnis", "Ekonomi", "uang", "finance", "business", "ekbis", "saham",
                    "keuangan", "makro", "bursa", "Finansial", "perbankan", "market",
                    "market-news", "banking", "economics", "crypto", "energi", "industri"):
            self.assertTrue(is_news_category(cat), f"{cat!r} should be a news category")
            self.assertTrue(is_finance_category(cat), f"{cat!r} should be a finance category")

    def test_hard_news_sections_are_news_but_not_finance(self):
        for cat in ("nasional", "politik", "hukum", "kriminal", "internasional", "daerah",
                    "megapolitan", "politik-dan-hukum", "pilkada", "militer", "nusantara"):
            self.assertTrue(is_news_category(cat), f"{cat!r} should be a news category")
            self.assertFalse(is_finance_category(cat), f"{cat!r} is not finance")

    def test_mixed_buckets_are_neither(self):
        # KUMPARAN `news` sampled 1-of-4 hard news; VIVA `news-sitemap` 0-of-4;
        # these are what the score (and SYS-37's probe) arbitrate.
        for cat in ("news", "berita", "news-sitemap", "sitemap", "pendidikan", "syariah",
                    "humaniora", "research", "mymoney", "csr", "kesehatan", "otomotif", None, ""):
            self.assertFalse(is_news_category(cat), f"{cat!r} must stay a mixed bucket")
            self.assertIsNone(category_gate(cat), f"{cat!r} must be scored")

    def test_exact_match_only_never_substring(self):
        self.assertFalse(is_news_category("bisnis-hiburan"))
        self.assertFalse(is_news_category("ekonomi-kreatif"))
        self.assertFalse(is_news_category("https://www.cnnindonesia.com/ekonomi/sitemap_news.xml"))

    def test_host_qualified_key_uses_its_section(self):
        # SRC-41 JPNN keys and SRC-34 INEWS keys.
        self.assertTrue(is_news_category("bali/politik"))
        self.assertTrue(is_news_category("jogja/kriminal"))
        self.assertTrue(is_finance_category("finance/keuangan"))
        self.assertFalse(is_news_category("bali/bali-terkini"))

    def test_deny_and_allow_vocabularies_are_disjoint(self):
        for name in NEWS_CATEGORIES:
            self.assertFalse(is_offtopic_category(name), f"{name!r} is in both the allow-set and the deny-list")
        self.assertFalse(NEWS_CATEGORIES_FINANCE & OFFTOPIC_CATEGORIES_EXACT)
        self.assertFalse(NEWS_CATEGORIES_HARD & OFFTOPIC_CATEGORIES_EXACT)

    def test_category_gate_is_the_one_decision(self):
        self.assertEqual(category_gate("hiburan"), "deny")
        self.assertEqual(category_gate("bisnis"), "allow")
        self.assertEqual(category_gate("nasional"), "allow")
        self.assertIsNone(category_gate("news"))

    def test_deny_wins_over_allow_for_a_value_matching_both(self):
        # The committed *names* are disjoint (asserted above), but a host-
        # qualified key (SRC-41 `<region>/<section>`, SRC-34 `finance/<leaf>`)
        # can carry a soft stem in one segment and an allow-set name in the
        # last: `hiburan/nasional` is denied by substring AND allowed by its
        # section. Deny must win -- the ordering is policy, not accident.
        # DBT-32 (#141): the old version of this test used `bali/sport`, which
        # never matched the allow-set, so swapping the two checks passed it.
        self.assertTrue(is_offtopic_category("hiburan/nasional"))
        self.assertTrue(is_news_category("hiburan/nasional"))
        self.assertEqual(category_gate("hiburan/nasional"), "deny")
        self.assertEqual(category_gate("https://olahraga.example.com/ekonomi"), "deny")
        self.assertEqual(category_gate("bali/sport"), "deny")
        self.assertEqual(category_gate("bali/politik"), "allow")


def _make_filter_without_loading_model(max_score=0.9, max_offtopic=0.0):
    filt = SemanticImportanceFilter.__new__(SemanticImportanceFilter)
    filt.model = MagicMock()
    filt.interests = ["Ekonomi"]
    filt.threshold = 0.35
    filt.margin = 0.035
    filt.interest_embeddings = MagicMock()
    filt.offtopic_interests = OFFTOPIC_INTERESTS
    filt.offtopic_embeddings = MagicMock()
    filt._score = MagicMock(return_value=(max_score >= 0.35 and max_offtopic + 0.035 < max_score, max_score, max_offtopic))
    return filt


class TestSemanticImportanceFilterCategoryGate(unittest.TestCase):
    """Category check must short-circuit before the model ever runs."""

    def test_offtopic_category_rejected_without_encoding(self):
        filt = _make_filter_without_loading_model()
        decision = filt.classify("some text", category="hiburan")
        self.assertFalse(decision.is_important)
        self.assertEqual(decision.gate, "deny")
        self.assertIsNone(decision.score_passed)
        filt._score.assert_not_called()
        self.assertFalse(filt.is_important("some text", category="hiburan"))

    def test_empty_text_rejected(self):
        filt = _make_filter_without_loading_model()
        self.assertFalse(filt.is_important("", category=None))
        self.assertEqual(filt.classify("", category="bisnis").gate, "empty")

    def test_news_category_saved_even_when_the_score_says_no(self):
        # SYS-35: world oil prices score 0.254 against the INTERESTS phrases.
        filt = _make_filter_without_loading_model(max_score=0.254)
        decision = filt.classify("Harga Minyak Dunia Turun Usai AS Ungkap Pipa Arab Saudi", category="bisnis")
        self.assertTrue(decision.is_important)
        self.assertEqual(decision.gate, "allow")
        self.assertFalse(decision.score_passed)
        self.assertAlmostEqual(decision.max_score, 0.254)
        self.assertTrue(filt.is_important("Harga Minyak Dunia Turun", category="bisnis"))

    def test_news_category_still_runs_the_score_for_the_recall_stat(self):
        filt = _make_filter_without_loading_model(max_score=0.254)
        filt.classify("Harga Minyak Dunia Turun", category="bisnis")
        filt._score.assert_called_once()

    def test_mixed_bucket_is_decided_by_the_score(self):
        below = _make_filter_without_loading_model(max_score=0.20)
        self.assertEqual(below.classify("x", category="news"), FilterDecision(False, "score", False, 0.20, 0.0))
        above = _make_filter_without_loading_model(max_score=0.60)
        self.assertEqual(above.classify("x", category="news").is_important, True)

    def test_is_important_is_a_thin_wrapper_over_classify(self):
        filt = _make_filter_without_loading_model(max_score=0.60)
        filt.classify = MagicMock(return_value=FilterDecision(True, "score", True, 0.6, 0.1))
        self.assertTrue(filt.is_important("x", category="news"))
        filt.classify.assert_called_once_with("x", "news")


class TestSemanticImportanceFilterRealModel(unittest.TestCase):
    """Real model, real off-topic anchors: verifies the margin actually
    separates a lifestyle/celebrity text from a finance one when category is
    unavailable (category=None) -- the defense-in-depth path for sources whose
    category is missing or not yet in the deny-list -- and that the SYS-35
    allow-set rescues the worked examples the score rejects."""

    @classmethod
    def setUpClass(cls):
        from newscrawler.core.constants import INTERESTS
        cls.filt = SemanticImportanceFilter(
            interests=INTERESTS,
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            offtopic_interests=OFFTOPIC_INTERESTS,
        )

    def test_celebrity_gossip_rejected_with_no_category(self):
        text = ("Ria Ricis Nangis Lihat Sapi Kurbannya Disembelih. Selebgram itu tak kuasa "
                "menahan tangis saat sapi kesayangannya disembelih di Idul Adha.")
        self.assertFalse(self.filt.is_important(text, category=None))

    def test_real_finance_headline_still_passes(self):
        text = ("Bank Indonesia Naikkan Suku Bunga Acuan 25 Basis Poin. Rapat Dewan Gubernur BI "
                "menahan inflasi yang masih tinggi di tengah pelemahan Rupiah.")
        self.assertTrue(self.filt.is_important(text, category=None))

    def test_sys35_worked_examples_pass_under_their_finance_category(self):
        """The eight SYS-35 rejects (real bodies score 0.20-0.34). They pass
        because of the category, not the score -- the score half of this
        Done-when transfers to SYS-37 (#121) per the owner's comment."""
        examples = [
            ("LIPUTAN6", "bisnis", "Harga Minyak Dunia Turun Usai AS Ungkap Pipa Arab Saudi Segera Beroperasi. "
             "Liputan6.com, Jakarta - Harga minyak dunia turun pada perdagangan Rabu setelah Amerika Serikat "
             "mengungkap pipa minyak Arab Saudi akan segera beroperasi. Harga minyak mentah West Texas Intermediate turun."),
            ("LIPUTAN6", "bisnis", "Produksi Pesawat Terhambat, Saham Boeing Turun Tajam. Saham Boeing turun tajam "
             "setelah perusahaan mengumumkan produksi pesawat 737 MAX terhambat masalah pemasok."),
            ("SUARA", "bisnis", "BI Jajaki Kerja Sama QRIS dengan 4 Negara Baru. Bank Indonesia menjajaki kerja sama "
             "pembayaran lintas negara berbasis QRIS dengan empat negara baru di kawasan Asia."),
            ("MERDEKA", "uang", "Utang Whoosh Akan Dilimpahkan Ke Kemenkeu Pertengahan September. Utang proyek kereta "
             "cepat Whoosh akan dilimpahkan ke Kementerian Keuangan pada pertengahan September."),
            ("TEMPO", "ekonomi", "DJP Gandeng Pertamina Perkuat Sistem Perpajakan. Direktorat Jenderal Pajak menggandeng "
             "Pertamina untuk memperkuat sistem perpajakan sektor energi."),
            ("VIVA", "bisnis", "Pintu Rilis Layanan VIP Private, Khusus Trader Aset Rp10 Miliar. Platform kripto Pintu "
             "meluncurkan layanan VIP Private bagi trader dengan aset di atas Rp10 miliar."),
            ("VIVA", "bisnis", "Bahlil: Perusahaan Rusia Mau Bangun Pabrik Alumina di Kalimantan. Menteri ESDM Bahlil "
             "Lahadalia menyebut perusahaan Rusia berminat membangun pabrik alumina di Kalimantan."),
            ("TIRTO", "ekonomi", "Rokok Ilegal Marak, Realisasi Pajak Rokok Jakarta Turun Rp37 M. Maraknya rokok ilegal "
             "membuat realisasi pajak rokok Jakarta turun Rp37 miliar tahun ini."),
        ]
        for source, category, text in examples:
            decision = self.filt.classify(text, category=category)
            self.assertTrue(decision.is_important, f"{source}/{category}: {text[:60]}")
            self.assertEqual(decision.gate, "allow")

    def test_sys34_regression_titles_are_rejected_by_their_category(self):
        for category, text in (
            ("fiction", "[PUISI] Barangkali Aku Butuh Jeda. Barangkali aku butuh jeda dari riuh yang tak kunjung reda."),
            ("korea", "3 Profesi Dilakoni Han So Hee di Film, Ada yang Jadi Pengacara. Han So Hee memerankan tiga profesi."),
            ("hype", "Harry Vaughan Umumkan Pernikahan dengan Nevy Tania. Aktor Harry Vaughan resmi menikah."),
            ("life", "7 Gaya OOTD Dewi Gita, Selalu Tampil Stunning. Penampilan Dewi Gita selalu memukau."),
            ("life", "5 Zodiak yang Punya Aura Pembawa Rezeki. Zodiak ini dipercaya membawa keberuntungan."),
        ):
            decision = self.filt.classify(text, category=category)
            self.assertFalse(decision.is_important, f"{category}: {text[:50]}")
            self.assertEqual(decision.gate, "deny")

    def test_sys34_poem_and_kdrama_are_measured_against_the_margin_too(self):
        """SYS-34 (d): the margin fallback passed a poem and three K-drama
        recaps on the live run. Record what it does on the same titles with
        no category, so a change to the score is measured against them and
        not only against SYS-31's six. This is not a guard on the margin --
        SYS-37 replaces it -- it is a guard that the category gate stays the
        thing that rejects them: whatever the score says, `deny` wins."""
        poem = "[PUISI] Barangkali Aku Butuh Jeda. Barangkali aku butuh jeda dari riuh yang tak kunjung reda."
        kdrama = "7 Perubahan Positif Tim 5 Setelah Konflik di The Ordinary Jackpot. Drama Korea ini makin seru."
        for text in (poem, kdrama):
            no_category = self.filt.classify(text, category=None)
            with_category = self.filt.classify(text, category="fiction")
            self.assertEqual(with_category.gate, "deny")
            self.assertFalse(with_category.is_important)
            # The score's own verdict is recorded on the decision either way.
            self.assertIn(no_category.gate, ("score",))


if __name__ == "__main__":
    unittest.main()
