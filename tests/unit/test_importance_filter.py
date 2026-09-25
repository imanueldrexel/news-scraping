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
2026-09-20.

SYS-37 (#121) / SYS-45 (#140): the cosine score is gone; the probe decides
everything the category gate does not deny -- news desks included (`allow`
means the score cannot reject, the probe can). Offline tests use a stub
probe; the real-encoder tests load the committed artifact and skip when
multilingual-e5-large is not cached locally.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

import pytest

from newscrawler.core.importance_filter import (
    FilterDecision,
    NEWS_CATEGORIES,
    NEWS_CATEGORIES_FINANCE,
    NEWS_CATEGORIES_HARD,
    OFFTOPIC_CATEGORIES_EXACT,
    SemanticImportanceFilter,
    category_gate,
    is_finance_category,
    is_news_category,
    is_offtopic_category,
)
from newscrawler.core.importance_probe import ImportanceProbe, ProbeArtifactError


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

    def test_sys49_opinion_buckets_are_denied(self):
        """SYS-49 (#147, owner 2026-09-23): an op-ed argues about an event, it
        is not one. All five live buckets were sampled (4 titles each, table on
        the ticket) and left category_vocabulary_not_denied.json in the same
        commit. The URL/host-qualified forms matter because a widened crawler
        reaches these sections through SRC-41's `<region>/<section>` keys."""
        for cat in (
            "opini", "opinion", "editorial", "editorials", "kolom", "kolom-pakar",
            "surat-pembaca", "scope", "tajuk", "tajuk-rencana",
            "bali/opini", "jabar/kolom", "https://www.mediaindonesia.com/editorials/sitemap.xml",
        ):
            self.assertTrue(is_offtopic_category(cat), f"{cat!r} should be off-topic")

    def test_sys49_opinion_stems_are_word_bounded(self):
        """SYS-42's rule applied to SYS-49's names: `scope` must not be found
        inside `horoscope`, and no stem may swallow an unrelated section.
        `analisis` is deliberately not denied -- a market-analysis desk reports
        as often as it argues and no sample was taken of one."""
        for cat in ("horoscope", "periskop", "kolombia", "opinionated", "analisis", "analisis-pasar"):
            self.assertFalse(is_offtopic_category(cat), f"{cat!r} should not be off-topic")

    def test_sys49_the_near_duplicate_oped_pair_now_gets_one_verdict(self):
        """The defect SYS-49 was filed on: two SINDONEWS `scope` analyses of the
        same war landed on opposite sides of tau (P(soft) 0.34 vs 0.47). The
        category decides now, so both are denied before the probe -- which is
        the only way near-identical texts can get a consistent verdict."""
        self.assertEqual(category_gate("scope"), "deny")
        self.assertEqual(category_gate("opini"), "deny")


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


def _make_filter_with_stub_probe(p_soft=0.1, topic="markets", confidence=0.8, threshold=0.39):
    """SYS-37: a filter whose probe and encoder are stubs -- offline, no model.
    The stub probe returns the same P(soft) for every row; the category gate
    and the batch plumbing are what is under test."""
    filt = SemanticImportanceFilter.__new__(SemanticImportanceFilter)
    filt.model = MagicMock()
    filt.model.encode.side_effect = lambda texts, **kw: [[0.0] * 4 for _ in texts]
    filt.model_name = "stub-encoder"
    probe = MagicMock()
    probe.dim = 4
    probe.soft_threshold = threshold
    probe.encoder_name = "stub-encoder"
    probe.predict.side_effect = lambda emb: [(p_soft < threshold, topic, confidence, p_soft) for _ in range(len(emb))]
    filt.probe = probe
    return filt


class TestSemanticImportanceFilterCategoryGate(unittest.TestCase):
    """Category check must short-circuit before the encoder ever runs; the
    probe decides everything else (SYS-45: a news desk included)."""

    def test_offtopic_category_rejected_without_encoding(self):
        filt = _make_filter_with_stub_probe()
        decision = filt.classify("some text", category="hiburan")
        self.assertFalse(decision.is_important)
        self.assertEqual(decision.gate, "deny")
        self.assertIsNone(decision.score_passed)
        self.assertIsNone(decision.topic)
        filt.model.encode.assert_not_called()
        filt.probe.predict.assert_not_called()
        self.assertFalse(filt.is_important("some text", category="hiburan"))

    def test_empty_text_rejected(self):
        filt = _make_filter_with_stub_probe()
        self.assertFalse(filt.is_important("", category=None))
        self.assertEqual(filt.classify("   ", category="bisnis").gate, "empty")
        filt.model.encode.assert_not_called()

    def test_news_category_is_decided_by_the_probe_not_waved_through(self):
        # SYS-45 (#140, owner 2026-09-21): `allow` means the *score* cannot
        # reject; the probe still can. A listicle on a finance desk is out.
        soft = _make_filter_with_stub_probe(p_soft=0.9)
        decision = soft.classify("7 Fakta Menarik Reksa Dana Syariah", category="bisnis")
        self.assertEqual(decision.gate, "allow")
        self.assertFalse(decision.is_important)
        self.assertFalse(decision.score_passed)
        self.assertAlmostEqual(decision.p_soft, 0.9)
        news = _make_filter_with_stub_probe(p_soft=0.1)
        decision = news.classify("Harga Minyak Dunia Turun Usai AS Ungkap Pipa Arab Saudi", category="bisnis")
        self.assertTrue(decision.is_important)
        self.assertEqual((decision.gate, decision.score_passed, decision.topic), ("allow", True, "markets"))

    def test_mixed_bucket_is_decided_by_the_probe(self):
        below = _make_filter_with_stub_probe(p_soft=0.7)
        d = below.classify("x", category="news")
        self.assertEqual((d.is_important, d.gate, d.score_passed), (False, "score", False))
        above = _make_filter_with_stub_probe(p_soft=0.2)
        self.assertTrue(above.classify("x", category="news").is_important)

    def test_topic_and_confidence_ride_on_every_scored_decision(self):
        filt = _make_filter_with_stub_probe(p_soft=0.2, topic="law_crime", confidence=0.66)
        d = filt.classify("Polisi Tangkap Pelaku", category=None)
        self.assertEqual((d.topic, d.topic_confidence, d.p_soft), ("law_crime", 0.66, 0.2))
        rejected = _make_filter_with_stub_probe(p_soft=0.8, topic="other_news")
        d = rejected.classify("x", category="news")
        self.assertEqual(d.topic, "other_news")   # set even when rejected: a caller that keeps it still gets a topic

    def test_uncertain_band(self):
        self.assertTrue(FilterDecision(True, "score", True, p_soft=0.36).in_uncertain_band)
        self.assertTrue(FilterDecision(False, "score", False, p_soft=0.65).in_uncertain_band)
        self.assertFalse(FilterDecision(True, "score", True, p_soft=0.10).in_uncertain_band)
        self.assertFalse(FilterDecision(False, "deny").in_uncertain_band)

    def test_classify_batch_is_the_one_decision_and_preserves_order(self):
        filt = _make_filter_with_stub_probe(p_soft=0.2)
        decisions = filt.classify_batch(
            ["news one", "", "soft desk", "news two"], ["news", "bisnis", "hiburan", "nasional"])
        self.assertEqual([d.gate for d in decisions], ["score", "empty", "deny", "allow"])
        self.assertEqual([d.is_important for d in decisions], [True, False, False, True])
        # only the two scorable rows were embedded, in one call
        filt.model.encode.assert_called_once()
        self.assertEqual(list(filt.model.encode.call_args[0][0]), ["news one", "news two"])
        with self.assertRaises(ValueError):
            filt.classify_batch(["a"], [])

    def test_classify_batch_raises_when_the_probe_returns_a_short_list(self):
        """DBT-36 (#152): `classify_batch` used to end in
        `[d for d in decisions if d is not None]`, so a probe returning one row
        fewer than it was given produced a silently shortened list. Every caller
        pairs it with its inputs by `zip`, and two of them delete articles and
        write `articles.topic`, so the gap would attribute every verdict after
        it to the wrong article -- undetectable afterwards. It must raise."""
        filt = _make_filter_with_stub_probe()
        filt.probe.predict.side_effect = lambda emb: [(True, "markets", 0.8, 0.1) for _ in range(len(emb) - 1)]
        with self.assertRaises(ProbeArtifactError) as ctx:
            filt.classify_batch(["a", "b", "c"], [None, None, None])
        self.assertIn("2 rows for 3", str(ctx.exception))

    def test_classify_batch_returns_one_decision_per_input_in_order(self):
        """The contract the callers rely on, pinned: same length, same order,
        including the rows the probe never sees (empty text, denied category)."""
        filt = _make_filter_with_stub_probe(p_soft=0.1)
        texts = ["news one", "", "gossip", "news two", "   "]
        cats = ["bisnis", "bisnis", "hiburan", "news", None]
        decisions = filt.classify_batch(texts, cats)
        self.assertEqual(len(decisions), len(texts))
        self.assertEqual([d.gate for d in decisions], ["allow", "empty", "deny", "score", "empty"])

    def test_is_important_is_a_thin_wrapper_over_classify(self):
        filt = _make_filter_with_stub_probe()
        filt.classify = MagicMock(return_value=FilterDecision(True, "score", True, "markets", 0.9, 0.1))
        self.assertTrue(filt.is_important("x", category="news", source="DETIK"))
        filt.classify.assert_called_once_with("x", "news", "DETIK")

    def test_missing_or_mismatched_artifact_is_a_hard_failure(self):
        with self.assertRaises(ProbeArtifactError):
            SemanticImportanceFilter(probe_dir=os.path.join(os.path.dirname(__file__), "no-such-dir"))
        probe = MagicMock(dim=4, encoder_name="stub", sidecar={}, soft_threshold=0.5)
        model = MagicMock()
        model.get_sentence_embedding_dimension.return_value = 5
        with self.assertRaises(ProbeArtifactError):
            SemanticImportanceFilter(probe=probe, model=model)
        probe.encoder_name = ""
        with self.assertRaises(ProbeArtifactError):
            SemanticImportanceFilter(probe=probe, model=MagicMock())


class TestCommittedProbeArtifact(unittest.TestCase):
    """The artifact in newscrawler/core/models/ is what the service loads.
    Offline: reads the sidecar, no encoder."""

    @classmethod
    def setUpClass(cls):
        cls.probe = ImportanceProbe.load()

    def test_artifact_matches_the_code_and_the_committed_gold_set(self):
        from newscrawler.core.filter_rubric import TOPICS
        from newscrawler.core.importance_probe import sha256_of_file
        self.assertEqual(self.probe.classes, list(TOPICS))
        self.assertEqual(self.probe.encoder_name, "intfloat/multilingual-e5-large")
        gold = os.path.join(os.path.dirname(__file__), "..", "fixtures", "filter_gold.jsonl")
        self.assertEqual(self.probe.sidecar["gold_sha256"], sha256_of_file(gold),
                         "the artifact was trained on a different filter_gold.jsonl than the one committed -- retrain")

    def test_sidecar_records_metrics_meeting_the_gates(self):
        # A fast smoke test on the sidecar's OWN record of itself -- it proves
        # the file says the right thing, not that the weights do. DBT-35 (#151):
        # the real verification is TestCommittedProbeGatesRecomputed below,
        # which executes the committed weights over the gold test split. Do not
        # read this one as evidence the artifact is accurate.
        gates = {"recall_finance": 0.95, "recall_general": 0.90, "precision_mixed": 0.90,
                 "precision_allow": 0.90, "topic_accuracy": 0.80}
        m = self.probe.sidecar["metrics_test"]
        for name, floor in gates.items():
            self.assertGreaterEqual(m[name], floor - 0.02, name)
        self.assertEqual(self.probe.sidecar["gate_tolerance"], 0.02)
        self.assertGreater(self.probe.sidecar["n_test"], 700)


def _load_real_filter():
    try:
        return SemanticImportanceFilter()
    except Exception as e:  # noqa: BLE001 -- encoder not cached on this machine
        raise unittest.SkipTest(f"real encoder unavailable offline: {e!r}")


class TestSemanticImportanceFilterRealModel(unittest.TestCase):
    """The committed probe on its real encoder. Slow (loads multilingual-e5-large,
    ~2 GB); skipped when the encoder is not cached locally. These are the SYS-35
    and SYS-34 worked examples through the real `classify` -- the ticket's
    Done-when, now judged by the probe rather than rescued by the category."""

    @classmethod
    def setUpClass(cls):
        cls.filt = _load_real_filter()

    def test_sys35_worked_examples_pass_with_a_finance_topic(self):
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
        from newscrawler.core.filter_rubric import TOPICS_FINANCE
        decisions = self.filt.classify_batch([t for _, _, t in examples], [c for _, c, _ in examples])
        for (source, category, text), d in zip(examples, decisions):
            self.assertTrue(d.is_important, f"{source}/{category}: {text[:60]} p_soft={d.p_soft:.2f}")
            self.assertEqual(d.gate, "allow")
            self.assertTrue(d.score_passed, f"the probe itself must keep {text[:50]}")
            self.assertIn(d.topic, TOPICS_FINANCE, f"{text[:50]} -> {d.topic}")

    def test_soft_examples_fail_by_probe_with_no_category(self):
        # No category: the deny-list cannot help; the probe alone must say soft.
        for text in (
            "[PUISI] Barangkali Aku Butuh Jeda. Barangkali aku butuh jeda dari riuh yang tak kunjung reda, "
            "dari langkah yang terus dipaksa. Aku ingin diam sejenak.",
            "Doa Hari Ini untuk Kelancaran Rezeki, Lengkap dengan Artinya. Berikut bacaan doa agar rezeki lancar "
            "yang bisa diamalkan setiap pagi beserta arti dan keutamaannya.",
            "Resep Ayam Goreng Kremes Renyah ala Rumahan, Bumbu Meresap Sempurna. Bahan-bahan: 1 ekor ayam, "
            "bawang putih, ketumbar, kunyit. Cara membuat: haluskan bumbu, marinasi ayam selama 30 menit.",
            "Hasil Liga Inggris: Arsenal Menang 3-1 atas Tottenham, Saka Cetak Dua Gol. Arsenal mengalahkan "
            "Tottenham Hotspur 3-1 di Emirates Stadium; Bukayo Saka mencetak dua gol dan Odegaard satu.",
            "7 Gaya OOTD Dewi Gita, Selalu Tampil Stunning dan Elegan. Penampilan Dewi Gita selalu memukau dengan "
            "padu padan busana yang chic; simak inspirasi gayanya berikut ini.",
        ):
            d = self.filt.classify(text, category=None)
            self.assertFalse(d.is_important, f"{text[:50]} p_soft={d.p_soft:.2f}")
            self.assertEqual(d.gate, "score")

    def test_sys34_regression_titles_are_rejected_by_their_category_before_the_probe(self):
        for category, text in (
            ("fiction", "[PUISI] Barangkali Aku Butuh Jeda. Barangkali aku butuh jeda dari riuh yang tak kunjung reda."),
            ("korea", "3 Profesi Dilakoni Han So Hee di Film, Ada yang Jadi Pengacara. Han So Hee memerankan tiga profesi."),
            ("hype", "Harry Vaughan Umumkan Pernikahan dengan Nevy Tania. Aktor Harry Vaughan resmi menikah."),
            ("life", "5 Zodiak yang Punya Aura Pembawa Rezeki. Zodiak ini dipercaya membawa keberuntungan."),
        ):
            d = self.filt.classify(text, category=category)
            self.assertEqual((d.is_important, d.gate), (False, "deny"), f"{category}: {text[:50]}")


if __name__ == "__main__":
    unittest.main()


class TestCommittedProbeGatesRecomputed(unittest.TestCase):
    """DBT-35 (#151): run the COMMITTED weights over the committed gold `test`
    split under the live rule, and check the five gates that were actually
    measured -- not the sidecar's record of them.

    What this catches that nothing else did: the weights and the sidecar
    drifting apart. An honest retrain that regresses never reaches a test,
    because the trainer refuses to write below its gates. A half-trained
    checkpoint, an artifact copied from an experiment branch, or a binary merge
    resolved the wrong way passes every other check -- shapes validate, the
    class list matches, the gold hash is unchanged -- while the live filter
    makes different decisions from the ones the sidecar advertises.

    The embedding matrix is committed (tests/fixtures/probe_test_embeddings.npz,
    763 x 1024 float32) and keyed by the encoder and the gold sha256, so this
    runs offline in ~2 s and an edited fixture invalidates it. That the matrix
    is genuine encoder output is the separate, slower check below -- otherwise
    the cache would just be the next unverified artifact.
    """

    @classmethod
    def setUpClass(cls):
        import numpy as np
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "scripts"))
        from newscrawler.core.filter_rubric import TOPICS
        from newscrawler.core.importance_probe import build_check_text, sha256_of_file
        import train_importance_probe as trainer

        cls.np, cls.trainer, cls.TOPICS = np, trainer, TOPICS
        cls.probe = ImportanceProbe.load()
        fixtures = os.path.join(os.path.dirname(__file__), "..", "fixtures")
        cls.gold_path = os.path.join(fixtures, "filter_gold.jsonl")
        with open(cls.gold_path, encoding="utf-8") as f:
            gold = [json.loads(line) for line in f if line.strip()]
        cls.test_rows = [r for r in gold if r["split"] == "test"]
        cls.texts = [build_check_text(r["headline"], r.get("body_head")) for r in cls.test_rows]
        cls.cache = np.load(os.path.join(fixtures, "probe_test_embeddings.npz"))
        cls.gold_sha = sha256_of_file(cls.gold_path)

    def test_the_embedding_matrix_belongs_to_this_gold_set_and_this_encoder(self):
        """The cache key. If any of these drifts the recomputation below would
        be measuring the wrong rows, so it must fail here first -- offline, with
        no encoder needed."""
        import hashlib
        self.assertEqual(str(self.cache["encoder"]), self.probe.encoder_name)
        self.assertEqual(str(self.cache["gold_sha256"]), self.gold_sha,
                         "the committed embeddings were built from a different filter_gold.jsonl -- rebuild them")
        self.assertEqual(int(self.cache["n"]), len(self.test_rows))
        self.assertEqual(self.cache["X"].shape, (len(self.test_rows), self.probe.dim))
        self.assertEqual(str(self.cache["texts_sha256"]),
                         hashlib.sha256("\n".join(self.texts).encode("utf-8")).hexdigest(),
                         "the gold test rows' text changed but the embeddings did not -- rebuild them")

    def _recompute(self):
        X = self.cache["X"]
        p_soft = self.probe.p_soft(X)
        topic_pred = self.trainer.topic_of(self.probe.topic_proba(X), list(self.TOPICS))
        return self.trainer.gate_metrics(self.test_rows, p_soft, topic_pred, self.probe.soft_threshold)

    def test_the_committed_weights_meet_every_gate(self):
        metrics = self._recompute()
        ok, failures = self.trainer.gates_pass(metrics)
        self.assertTrue(ok, "the committed probe does not meet its gates: %s" % "; ".join(failures))

    def test_the_committed_weights_reproduce_the_sidecar(self):
        """The drift check. If the weights and the sidecar disagree, one of them
        is lying about what the live filter does."""
        recomputed = self._recompute()
        recorded = self.probe.sidecar["metrics_test"]
        for name in self.trainer.GATES:
            self.assertAlmostEqual(
                recomputed[name], recorded[name], places=9,
                msg="%s: weights say %.10f, sidecar claims %.10f -- the artifact and its sidecar have "
                    "drifted apart (half-trained checkpoint? artifact from another branch?)"
                    % (name, recomputed[name], recorded[name]))

    def test_the_live_rule_is_what_was_measured(self):
        """The recomputation must apply the category deny-gate, not the bare
        probe -- otherwise it is not the decision the pipeline makes."""
        denied = [i for i, r in enumerate(self.test_rows) if category_gate(r.get("category")) == "deny"]
        self.assertTrue(denied, "no denied rows in the test split -- this assertion proves nothing")
        pred = self.trainer.live_decision(self.probe.p_soft(self.cache["X"]),
                                          [r.get("category") for r in self.test_rows],
                                          self.probe.soft_threshold)
        self.assertFalse(any(pred[i] for i in denied), "a deny-category row was kept")


class TestCommittedEmbeddingsAreRealEncoderOutput(unittest.TestCase):
    """DBT-35 (#151) fix 2: the committed matrix above makes the gate check fast,
    which only helps if the matrix is genuinely what the encoder produces. This
    re-encodes a sample of the gold test rows through the encoder the sidecar
    names and compares. Slow (loads multilingual-e5-large); skipped only when
    the encoder is not available locally -- the gate checks above never skip."""

    N_SAMPLE = 24

    @pytest.mark.timeout(1800)
    def test_sampled_rows_reencode_to_the_committed_vectors(self):
        import hashlib
        import random
        import numpy as np
        from newscrawler.core.importance_probe import build_check_text, embed_for_probe

        probe = ImportanceProbe.load()
        fixtures = os.path.join(os.path.dirname(__file__), "..", "fixtures")
        cache = np.load(os.path.join(fixtures, "probe_test_embeddings.npz"))
        with open(os.path.join(fixtures, "filter_gold.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows = [r for r in rows if r["split"] == "test"]
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(probe.encoder_name)
        except Exception as e:  # noqa: BLE001 -- encoder not cached on this machine
            raise unittest.SkipTest("encoder %r unavailable offline: %r" % (probe.encoder_name, e))

        idx = random.Random(20260923).sample(range(len(rows)), min(self.N_SAMPLE, len(rows)))
        fresh = embed_for_probe(model, [build_check_text(rows[i]["headline"], rows[i].get("body_head")) for i in idx],
                                model_name=probe.encoder_name)
        delta = float(np.abs(fresh - cache["X"][idx]).max())
        self.assertLess(delta, 1e-4,
                        "committed embeddings differ from a fresh encode by %.2e -- they are not this encoder's "
                        "output for these rows" % delta)
