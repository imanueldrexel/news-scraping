"""SYS-36 (#120): the gold-set builder's pure parts -- stratum assignment,
allocation, the round-robin draw, the split, label parsing -- and the rubric
module's consistency rules. Offline; the Gemini call is not exercised here."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import pytest  # noqa: E402

from label_filter_gold import (  # noqa: E402
    STRATA_TARGETS, STRATUM_ORDER, allocate, assign_splits, assign_stratum, batch_payload, draw, parse_labels,
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


class TestAssignSplits:
    def test_twenty_percent_test_per_stratum(self):
        rows = [{"sitemap_id": i, "stratum": "finance_reject"} for i in range(100)] + \
               [{"sitemap_id": 100 + i, "stratum": "soft_save"} for i in range(10)]
        assign_splits(rows, random.Random(3))
        fr = [r for r in rows if r["stratum"] == "finance_reject"]
        ss = [r for r in rows if r["stratum"] == "soft_save"]
        assert sum(r["split"] == "test" for r in fr) == 20
        assert sum(r["split"] == "test" for r in ss) == 2


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
