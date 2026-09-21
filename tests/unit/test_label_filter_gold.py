"""SYS-36 (#120): the gold-set builder's pure parts -- stratum assignment,
allocation, the round-robin draw, the split, label parsing -- and the rubric
module's consistency rules. Offline; the Gemini call is not exercised here."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import pytest  # noqa: E402

from label_filter_gold import (  # noqa: E402
    GOLD_PATH, SAMPLE_PATH, STRATA_TARGETS, STRATUM_ORDER, allocate, assign_splits, assign_stratum, batch_payload,
    conflicting_label_headlines, dedupe_within_source, draw, frozen_has_body, headline_groups, merge_bodies,
    normalise_headline, parse_labels, read_jsonl, reassign_strata, refresh_categories, refresh_rows, repair_split_leaks,
)
from newscrawler.core.filter_rubric import (  # noqa: E402
    TOPICS, TOPICS_FINANCE, TOPICS_NEWS, TOPIC_SOFT, build_label_prompt, is_valid_label,
)


class TestRubric:
    def test_topics_are_the_prd_list_plus_soft(self):
        assert TOPICS_FINANCE == ["markets", "macro_policy", "corporate", "commodities_energy", "consumer"]
        assert set(TOPICS_NEWS) == {"politics_government", "law_crime", "disaster_accident", "international",
                                    "tech_science", "health_education", "other_news"}
        assert TOPICS[-1] == TOPIC_SOFT and len(TOPICS) == 13

    def test_soft_iff_not_news(self):
        assert is_valid_label(False, "soft")
        assert is_valid_label(True, "markets")
        assert not is_valid_label(True, "soft")
        assert not is_valid_label(False, "markets")
        assert not is_valid_label("true", "markets")
        assert not is_valid_label(True, "sports")

    def test_prompt_carries_the_rubric_and_the_rows(self):
        prompt = build_label_prompt('[{"id": 1, "headline": "Harga Minyak Turun", "body_head": null}]')
        assert "NEWS-WORTHY (is_news = true)" in prompt
        assert "AND SPORTS" in prompt
        assert "Harga Minyak Turun" in prompt
        assert ", ".join(TOPICS) in prompt

    def test_sys46_boundaries_are_in_the_prompt(self):
        # Owner decision 2026-09-21 (SYS-46 #142): the two hand-check rows the
        # owner called soft against the old wording are the rubric's worked
        # negatives now, and the old "a celebrity in a court case is news"
        # sentence is gone.
        prompt = " ".join(build_label_prompt("[]").split())   # the rubric is hard-wrapped
        assert "school and campus regulations and guidance" in prompt
        assert '"Kemenag Batasi Penggunaan HP di Sekolah" is soft' in prompt
        assert "celebrity's OWN criminal case" in prompt
        assert '"Rizky Billar Ditetapkan Tersangka KDRT" is soft' in prompt
        assert "A celebrity in a court case is news" not in prompt
        assert "not a celebrity's own case: soft" in prompt
        assert "not school rules: soft" in prompt


class TestAssignStratum:
    def test_finance_reject_is_the_sys35_population(self):
        assert assign_stratum("LIPUTAN6", "bisnis", "rejected_filter", False, "Harga Minyak Dunia Turun") == "finance_reject"

    def test_soft_save_is_the_sys34_population(self):
        assert assign_stratum("IDNTIMES", "hype", "saved", True, "Harry Vaughan Umumkan Pernikahan") == "soft_save"

    def test_religion_boundary_by_headline(self):
        assert assign_stratum("TVONENEWS", "news", "rejected_filter", False, "Doa Hari Ini untuk Kelancaran Rezeki") == "religion_boundary"
        assert assign_stratum("KOMPAS", "nasional", "saved", True, "Kemenag Tambah Kuota Haji 2026") == "religion_boundary"

    def test_econ_politics_boundary_by_headline(self):
        assert assign_stratum("VIVA", "berita", "pending", False, "Menkeu Purbaya Soal Utang Whoosh") == "econ_politics_boundary"

    def test_viva_general_sections(self):
        assert assign_stratum("VIVA", "militer", "pending", False, "Meksiko Kirim Tentara") == "viva_general"
        assert assign_stratum("VIVA", "https://wisata.viva.co.id/sitemap/news/news-sitemap.xml", "pending", False, "Pantai") == "viva_general"
        assert assign_stratum("VIVA", "bisnis", "pending", False, "Rupiah") == "finance_pending"

    def test_mixed_buckets(self):
        assert assign_stratum("KUMPARAN", "news", "rejected_filter", False, "Kebakaran Kemayoran") == "mixed_bucket"
        assert assign_stratum("JPNN", "https://bali.jpnn.com/sitemap_post_politik.xml", "saved", True, "x") == "mixed_bucket"
        assert assign_stratum("KOMPAS", "makassar", "saved", True, "Banjir di Makassar") == "mixed_bucket"

    def test_finance_saved_and_pending(self):
        assert assign_stratum("TEMPO", "ekonomi", "saved", True, "IHSG Menguat") == "finance_saved"
        assert assign_stratum("TEMPO", "ekonomi", "pending", False, "IHSG Menguat") == "finance_pending"

    def test_hard_news_and_soft_category(self):
        assert assign_stratum("KOMPAS", "nasional", "rejected_filter", False, "Banjir Jakarta") == "hard_news"
        assert assign_stratum("OKEZONE", "celebrity", "pending", False, "Sinopsis Sinetron") == "soft_category"

    def test_every_stratum_name_is_a_target(self):
        for s in ("finance_reject", "soft_save", "religion_boundary", "econ_politics_boundary", "viva_general",
                  "mixed_bucket", "finance_saved", "finance_pending", "hard_news", "soft_category", "other"):
            assert s in STRATUM_ORDER


class TestAllocate:
    def test_targets_sum_to_size_when_available(self):
        counts = {name: 10_000 for name in STRATUM_ORDER}
        alloc = allocate(counts, 4000)
        assert sum(alloc.values()) == 4000
        assert alloc["finance_reject"] == 600 and alloc["mixed_bucket"] == 900

    def test_shortfall_goes_to_mixed_bucket(self):
        counts = {name: 10_000 for name in STRATUM_ORDER}
        counts["soft_save"] = 30
        alloc = allocate(counts, 4000)
        assert alloc["soft_save"] == 30
        assert alloc["mixed_bucket"] == 900 + 170
        assert sum(alloc.values()) == 4000

    def test_scales_to_a_smaller_size(self):
        counts = {name: 10_000 for name in STRATUM_ORDER}
        alloc = allocate(counts, 400)
        assert sum(alloc.values()) == 400
        assert alloc["finance_reject"] == 60


class TestDraw:
    def _rows(self, cell, n):
        source, category, status = cell
        return [{"sitemap_id": f"{category}-{i}", "source": source, "category": category, "crawl_status": status}
                for i in range(n)]

    def test_round_robin_does_not_let_a_giant_cell_crowd_out_a_small_one(self):
        rows = self._rows(("VIVA", "blog", "pending"), 1000) + self._rows(("VIVA", "militer", "pending"), 20)
        out = draw(rows, 40, random.Random(1))
        cats = [r["category"] for r in out]
        assert cats.count("militer") == 20 and cats.count("blog") == 20

    def test_seeded_and_capped(self):
        rows = self._rows(("A", "x", "pending"), 50)
        a = draw(rows, 10, random.Random(7))
        b = draw(rows, 10, random.Random(7))
        assert [r["sitemap_id"] for r in a] == [r["sitemap_id"] for r in b]
        assert len(draw(rows, 500, random.Random(7))) == 50


def _row(sid, source="INEWS", headline=None, category="news", status="rejected_filter", body=None, **extra):
    r = {"sitemap_id": sid, "source": source, "category": category, "headline": headline or f"Headline {sid}",
         "crawl_status": status, "body_head": body, "has_body": body is not None}
    r.update(extra)
    return r


class TestAssignSplits:
    def test_twenty_percent_test_per_stratum(self):
        rows = [_row(i, stratum="finance_reject") for i in range(100)] + \
               [_row(100 + i, stratum="soft_save") for i in range(10)]
        assign_splits(rows, random.Random(3))
        fr = [r for r in rows if r["stratum"] == "finance_reject"]
        ss = [r for r in rows if r["stratum"] == "soft_save"]
        assert sum(r["split"] == "test" for r in fr) == 20
        assert sum(r["split"] == "test" for r in ss) == 2

    def test_same_headline_never_straddles_the_split(self):
        """SYS-43: 30 copies of one syndicated headline spread over two strata
        and 70 distinct rows -- every copy lands on one side, whichever seed."""
        for seed in range(20):
            rows = [_row(i, source=f"S{i}", headline="Moment Hangat Presiden Prabowo di Gontor", stratum="mixed_bucket")
                    for i in range(15)]
            rows += [_row(100 + i, source=f"S{i}", headline="moment hangat  presiden prabowo di gontor ",
                          stratum="econ_politics_boundary") for i in range(15)]
            rows += [_row(200 + i, stratum="mixed_bucket") for i in range(70)]
            assign_splits(rows, random.Random(seed))
            sides = {r["split"] for r in rows if normalise_headline(r["headline"]) == "moment hangat presiden prabowo di gontor"}
            assert len(sides) == 1, f"seed {seed}: group straddles {sides}"
            test_keys = {normalise_headline(r["headline"]) for r in rows if r["split"] == "test"}
            train_keys = {normalise_headline(r["headline"]) for r in rows if r["split"] == "train"}
            assert not (test_keys & train_keys)

    def test_quota_still_roughly_twenty_percent_with_groups(self):
        rows = [_row(i, source=f"S{i}", headline="dup", stratum="a") for i in range(10)] + \
               [_row(100 + i, stratum="a") for i in range(90)]
        assign_splits(rows, random.Random(5))
        n_test = sum(r["split"] == "test" for r in rows)
        # 20 wanted; the 10-row group is all-or-nothing, so 20 or 10..29 depending on where it fell.
        assert 10 <= n_test <= 29


class TestDedupeWithinSource:
    def test_keeps_body_row_else_lowest_id_within_a_source(self):
        rows = [_row(5, headline="A"), _row(3, headline="a "), _row(9, headline="A", body="text"), _row(7, headline="B")]
        kept, dropped = dedupe_within_source(rows)
        assert [r["sitemap_id"] for r in kept] == [9, 7]
        assert sorted(r["sitemap_id"] for r in dropped) == [3, 5]
        rows = [_row(5, headline="A"), _row(3, headline="A")]
        kept, _ = dedupe_within_source(rows)
        assert [r["sitemap_id"] for r in kept] == [3]

    def test_cross_source_copies_are_both_kept(self):
        rows = [_row(1, source="INEWS", headline="Wire copy"), _row(2, source="KOMPAS", headline="wire copy")]
        kept, dropped = dedupe_within_source(rows)
        assert len(kept) == 2 and dropped == []

    def test_normalisation(self):
        assert normalise_headline("  Harga   Minyak\tTurun ") == "harga minyak turun"
        assert normalise_headline(None) == ""


class TestRefreshHelpers:
    def test_refresh_categories_overwrites_only_changed_and_known_ids(self):
        rows = [_row(1, category="https://bali.jpnn.com/sitemap_post_politik.xml"), _row(2, category="ekonomi"), _row(3, category="x")]
        n = refresh_categories(rows, {1: "bali/politik", 2: "ekonomi"})
        assert n == 1
        assert rows[0]["category"] == "bali/politik" and rows[1]["category"] == "ekonomi" and rows[2]["category"] == "x"

    def test_reassign_strata_moves_a_refreshed_hard_news_row_out_of_mixed_bucket(self):
        rows = [_row(1, source="JPNN", category="bali/politik", headline="Banjir Bandang", stratum="mixed_bucket"),
                _row(2, source="KUMPARAN", category="news", headline="Kebakaran", stratum="mixed_bucket")]
        assert reassign_strata(rows) == 1
        assert rows[0]["stratum"] == "hard_news" and rows[1]["stratum"] == "mixed_bucket"

    def test_repair_split_leaks_moves_a_straddling_group_to_train(self):
        rows = [_row(1, source="A", headline="Dup", split="test"), _row(2, source="B", headline="dup", split="train"),
                _row(3, source="C", headline="Solo", split="test"), _row(4, source="D", headline="Only", split="test"),
                _row(5, source="E", headline="only", split="test")]
        assert repair_split_leaks(rows) == 1
        assert rows[0]["split"] == "train" and rows[2]["split"] == "test"
        assert rows[3]["split"] == "test" and rows[4]["split"] == "test"  # same side already: untouched

    def test_conflicting_label_headlines(self):
        gold = [_row(1, source="S1", headline="Gontor", is_news=True), _row(2, source="S2", headline="gontor", is_news=False),
                _row(3, source="S1", headline="Persib", is_news=False), _row(4, source="S3", headline="persib", is_news=False),
                _row(5, headline="Solo", is_news=True)]
        assert conflicting_label_headlines(gold) == ["gontor"]
        assert set(headline_groups(gold)) == {"gontor", "persib"}


class TestMergeBodies:
    def test_rows_that_gain_a_body_are_updated_and_unlabelled_others_untouched(self):
        sample = [_row(1, headline="A"), _row(2, headline="B", body="old body"), _row(3, headline="C"), _row(4, headline="D")]
        gold = [dict(s, is_news=True, topic="markets", labeller="m", labelled_at="t") for s in sample]
        fetched = [{"sitemap_id": 1, "body_head": "fetched one"}, {"sitemap_id": 2, "body_head": "fetched two"},
                   {"sitemap_id": 3, "body_head": None, "error": "404"}]
        new_sample, new_gold, counts = merge_bodies(sample, gold, fetched)
        by = {r["sitemap_id"]: r for r in new_sample}
        assert by[1]["body_head"] == "fetched one" and by[1]["has_body"] is True and by[1]["had_body_at_freeze"] is False
        assert by[2]["body_head"] == "old body" and by[2]["had_body_at_freeze"] is True   # already had one: untouched
        assert by[3]["has_body"] is False and by[4]["has_body"] is False
        assert [g["sitemap_id"] for g in new_gold] == [2, 3, 4]                              # row 1 re-labelled later
        assert counts == {"rows_with_fetched_body": 2, "sample_rows_updated": 1, "gold_rows_unlabelled_for_relabel": 1,
                          "fetched_for_rows_that_already_had_a_body": 1}

    def test_stratum_stays_frozen_after_a_body_arrives(self):
        r = _row(1, source="LIPUTAN6", category="bisnis", headline="Harga Minyak", stratum="finance_reject")
        merge_bodies([r], [], [{"sitemap_id": 1, "body_head": "body"}])
        assert r["has_body"] is True and frozen_has_body(r) is False
        assert reassign_strata([r]) == 0 and r["stratum"] == "finance_reject"

    def test_merge_is_idempotent(self):
        sample = [_row(1, headline="A")]
        gold = [dict(sample[0], is_news=True, topic="markets", labeller="m", labelled_at="t")]
        fetched = [{"sitemap_id": 1, "body_head": "fetched"}]
        s1, g1, _ = merge_bodies(sample, gold, fetched)
        g1 = [dict(s1[0], is_news=False, topic="soft", labeller="m", labelled_at="t2")]       # re-labelled
        s2, g2, c2 = merge_bodies(s1, g1, fetched)
        assert s2 == s1 and g2 == g1 and c2["sample_rows_updated"] == c2["gold_rows_unlabelled_for_relabel"] == 0


class TestRefreshRows:
    def test_end_to_end_on_a_miniature_of_the_2026_09_20_fixture(self):
        sample = [
            # 3 INEWS mirror copies of one headline (2 labelled news, 1 soft) -> keep lowest id, unlabel.
            _row(10, headline="Prabowo di Gontor", stratum="econ_politics_boundary", split="train"),
            _row(11, headline="prabowo di gontor", stratum="econ_politics_boundary", split="test"),
            _row(12, headline="Prabowo  di Gontor", stratum="econ_politics_boundary", split="train"),
            # 2 copies labelled the same way -> keep the one with a body, label kept.
            _row(20, headline="Kemenag Batasi HP", stratum="religion_boundary", split="test"),
            _row(21, headline="Kemenag Batasi HP", stratum="religion_boundary", split="train", body="Kemenag ..."),
            # JPNN stale URL category -> bali/politik -> hard_news; label kept.
            _row(30, source="JPNN", category="https://bali.jpnn.com/sitemap_post_politik.xml", headline="Banjir Bandang Jembrana",
                 stratum="mixed_bucket", split="test"),
            # Cross-source copy straddling the split -> both to train.
            _row(40, source="KOMPAS", category="nasional", headline="Wire Copy", stratum="hard_news", split="test"),
            _row(41, source="CNBC", category="market", headline="wire copy", stratum="finance_pending", status="pending", split="train"),
            # Untouched row.
            _row(50, source="VIVA", category="militer", headline="Latihan TNI", status="pending", stratum="viva_general", split="test"),
        ]
        gold = [dict(s, is_news=n, topic=("politics_government" if n else "soft"), labeller="m", labelled_at="t")
                for s, n in zip(sample, [True, False, True, True, True, True, True, True, True])]
        current = {r["sitemap_id"]: r["category"] for r in sample}
        current[30] = "bali/politik"

        new_sample, new_gold, counts = refresh_rows(sample, gold, current)

        assert counts["conflicting_headline_groups"] == 1
        assert counts["categories_refreshed"] == 1
        assert counts["strata_reassigned"] == 1
        assert counts["duplicate_rows_dropped"] == 3          # 11, 12, 20
        assert counts["split_rows_moved_to_train"] == 1       # 40
        assert counts["gold_rows_unlabelled_for_relabel"] == 1  # 10
        assert [r["sitemap_id"] for r in new_sample] == [10, 21, 30, 40, 41, 50]
        assert [r["sitemap_id"] for r in new_gold] == [21, 30, 40, 41, 50]
        by_id = {r["sitemap_id"]: r for r in new_gold}
        assert by_id[30]["category"] == "bali/politik" and by_id[30]["stratum"] == "hard_news" and by_id[30]["split"] == "test"
        assert by_id[40]["split"] == "train" and by_id[41]["split"] == "train"
        assert by_id[21]["is_news"] is True and by_id[21]["has_body"] is True
        assert headline_groups([r for r in new_sample if r["source"] == "INEWS"]) == {}
        assert conflicting_label_headlines(new_gold) == []

    def test_refresh_is_idempotent(self):
        sample = [_row(1, headline="A", stratum="mixed_bucket", split="train"), _row(2, headline="B", stratum="mixed_bucket", split="test")]
        gold = [dict(s, is_news=True, topic="other_news", labeller="m", labelled_at="t") for s in sample]
        s1, g1, c1 = refresh_rows(sample, gold, {1: "news", 2: "news"})
        s2, g2, c2 = refresh_rows(s1, g1, {1: "news", 2: "news"})
        assert (s1, g1) == (s2, g2)
        assert c2["duplicate_rows_dropped"] == c2["split_rows_moved_to_train"] == c2["gold_rows_unlabelled_for_relabel"] == 0


@pytest.mark.skipif(not (os.path.exists(GOLD_PATH) and os.path.exists(SAMPLE_PATH)), reason="fixtures not present")
class TestCommittedGoldFixture:
    """SYS-43 / SYS-44 (#138 / #139) Done-when, pinned on the committed files.
    Every one of these failed on the 2026-09-20 fixture as first committed."""

    @pytest.fixture(scope="class")
    def files(self):
        return read_jsonl(SAMPLE_PATH), read_jsonl(GOLD_PATH)

    def test_no_same_source_duplicate_headlines(self, files):
        _, gold = files
        dups = [k for k, n in __import__("collections").Counter(
            (r["source"], normalise_headline(r["headline"])) for r in gold).items() if n > 1]
        assert dups == [], f"{len(dups)} duplicate (source, headline) groups, e.g. {dups[:3]}"

    def test_no_test_headline_appears_in_train(self, files):
        _, gold = files
        train = {normalise_headline(r["headline"]) for r in gold if r["split"] == "train"}
        leaks = [r["headline"] for r in gold if r["split"] == "test" and normalise_headline(r["headline"]) in train]
        assert leaks == [], f"{len(leaks)} test rows also in train, e.g. {leaks[:3]}"

    def test_no_conflicting_labels_on_a_repeated_headline(self, files):
        _, gold = files
        assert conflicting_label_headlines(gold) == []

    def test_no_url_category_on_a_source_whose_crawler_names_its_branches(self, files):
        # SYS-44: CNN and JPNN name every branch (branch_name_from_url); a URL
        # there is a stale value from before fix_url_shaped_categories.py.
        # VIVA/INEWS still carry URL categories in the DB (SRC-33 / SRC-29) and
        # are not asserted here -- they go stale the same way when those land.
        from newscrawler.core.crawler_dict_list import CRAWLER_DICT
        named = {n for n, c in CRAWLER_DICT.items() if hasattr(c, "branch_name_from_url")}
        assert {"CNN", "JPNN"} <= named
        _, gold = files
        stale = [(r["source"], r["category"]) for r in gold if r["source"] in named and (r["category"] or "").startswith("http")]
        assert stale == [], f"{len(stale)} stale URL categories, e.g. {stale[:3]}"

    def test_stratum_is_consistent_with_category_and_frozen_status(self, files):
        # The stratum on every row is what assign_stratum says for its
        # (refreshed) category and its frozen crawl_status/has_body/headline.
        sample, gold = files
        wrong = [(r["sitemap_id"], r["stratum"], assign_stratum(r["source"], r["category"], r["crawl_status"], frozen_has_body(r), r["headline"]))
                 for r in sample]
        wrong = [w for w in wrong if w[1] != w[2]]
        assert wrong == [], f"{len(wrong)} rows whose stratum does not match their category, e.g. {wrong[:3]}"

    def test_gold_rows_agree_with_the_sample(self, files):
        sample, gold = files
        by_id = {r["sitemap_id"]: r for r in sample}
        assert all(g["sitemap_id"] in by_id for g in gold)
        mism = [g["sitemap_id"] for g in gold
                if (g["category"], g["stratum"], g["split"], g["headline"]) !=
                (by_id[g["sitemap_id"]]["category"], by_id[g["sitemap_id"]]["stratum"],
                 by_id[g["sitemap_id"]]["split"], by_id[g["sitemap_id"]]["headline"])]
        assert mism == []
        assert len(gold) >= 3000


class TestParseLabels:
    BATCH = [{"sitemap_id": 1, "headline": "a", "body_head": None}, {"sitemap_id": 2, "headline": "b", "body_head": "x"}]

    def test_valid_response(self):
        raw = '[{"id": 1, "is_news": true, "topic": "markets"}, {"id": 2, "is_news": false, "topic": "soft"}]'
        labels, problems = parse_labels(raw, self.BATCH)
        assert labels == {1: (True, "markets"), 2: (False, "soft")}
        assert problems == []

    def test_code_fences_and_string_booleans_are_tolerated(self):
        raw = '```json\n[{"id": 1, "is_news": "true", "topic": "corporate"}]\n```'
        labels, problems = parse_labels(raw, self.BATCH)
        assert labels == {1: (True, "corporate")}
        assert any("id 2" in p for p in problems)

    def test_inconsistent_label_is_rejected_not_stored(self):
        raw = '[{"id": 1, "is_news": true, "topic": "soft"}, {"id": 2, "is_news": false, "topic": "law_crime"}]'
        labels, problems = parse_labels(raw, self.BATCH)
        assert labels == {}
        assert len(problems) == 2

    def test_unknown_id_and_garbage(self):
        assert parse_labels("not json", self.BATCH) == ({}, ["JSON parse error: Expecting value: line 1 column 1 (char 0)"])
        labels, problems = parse_labels('[{"id": 99, "is_news": true, "topic": "markets"}]', self.BATCH)
        assert labels == {} and "unknown id 99" in problems

    def test_payload_is_id_headline_body(self):
        assert batch_payload(self.BATCH) == '[{"id": 1, "headline": "a", "body_head": null}, {"id": 2, "headline": "b", "body_head": "x"}]'


class TestReadHandcheckCsv:
    """The owner fills the hand-check in Excel, which writes a UTF-8 BOM, a
    `;` delimiter and TRUE/FALSE upper-cased. The reader must not care."""

    def _write(self, tmp_path, text, encoding="utf-8-sig"):
        p = tmp_path / "hc.csv"
        with open(p, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return str(p)

    def test_excel_semicolon_with_bom(self, tmp_path):
        from label_filter_gold import read_handcheck_csv
        rows = read_handcheck_csv(self._write(
            tmp_path, "check;sitemap_id;headline;model_is_news;human_is_news\r\nis_news;1;A, b;True;FALSE\r\n"))
        assert rows == [{"check": "is_news", "sitemap_id": "1", "headline": "A, b",
                         "model_is_news": "True", "human_is_news": "FALSE"}]

    def test_plain_comma_without_bom_still_works(self, tmp_path):
        from label_filter_gold import read_handcheck_csv
        rows = read_handcheck_csv(self._write(
            tmp_path, 'check,sitemap_id,headline,model_is_news,human_is_news\nis_news,1,"A; b",True,true\n', "utf-8"))
        assert rows[0]["headline"] == "A; b" and rows[0]["human_is_news"] == "true"
