"""SYS-67 (#215): the summarizer says which of a section's clusters tell one story, and the
section shows at most NEWSLETTER_MAX_CLUSTERS_PER_STORY of each.

The headlines are the 2026-09-28 law_crime section: five clusters of the Lapas Cibinong scandal
(DPR hearing, KPK statement, the Jimmy Masrin photo, the Dirjen's orders, the state-asset
question) beside three unrelated cases -- and the model's real answer for them."""
import json
import logging
from datetime import date
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_generator as ng
import newscrawler.core.story_grouping as sg
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError

SECTION = [
    ["Komisi XIII DPR Cecar Dirjenpas Soal Hunian Mewah Lapas Cibinong", "6 Kesimpulan Hasil Rapat DPR dan Ditjenpas"],
    ["KPK Cium Aroma Suap di Balik Fasilitas Mewah Lapas Cibinong", "KPK Periksa Bobby Rizaldi soal BPK Muara Enim"],
    ["KPK Beber Kantor Pertanahan di Jatim Setor Uang Haram ke Kanwil BPN", "KPK Temukan Uang Dolar Saat Geledah BPN Jatim"],
    ["Remaja Makassar Tewas Diduga Tertembak Saat Tawuran", "Polisi Uji Balistik Tewasnya Remaja"],
    ["Foto Jimmy Masrin Ada di Rumah Dinas Kasimamtib Lapas IIA Cibinong", "DPR Pertanyakan Foto Jimmy Masrin"],
    ["Kejagung Tahan Eks Sekjen ESDM dalam Kasus Korupsi Nikel", "Kejagung Amankan Tersangka ke-5 Kasus Korupsi Nikel"],
    ["Dirjen PAS Perintahkan Bongkar Bangunan Tak Sesuai Peruntukan di Lapas", "Dirjen PAS Klaim Tak Ada Klaster Mewah"],
    ["13 Rumah Mewah di Lapas Cibinong Tak Tercatat sebagai Aset Negara", "Miras di Lapas Cibinong Milik Pribadi Kasi Kamtib"],
]
REAL_ANSWER = '{"grup": [[0,1,4,6,7],[2],[3],[5]]}'


def _clusters(headline_groups=SECTION):
    return [{"headline": g[0], "sources": ["A", "B"], "articles": [{"headline": h, "source": "A"} for h in g]}
            for g in headline_groups]


class FakeSummarizer:
    name = "fake-model"

    def __init__(self, group_answer=REAL_ANSWER, summary="- ringkasan"):
        self.group_answer = group_answer
        self.summary = summary
        self.prompts = []

    def summarize(self, prompt):
        self.prompts.append(prompt)
        answer = self.group_answer if "Balas HANYA dengan JSON" in prompt else self.summary
        if isinstance(answer, Exception):
            raise answer
        return answer


class TestParseGroups:
    def test_the_models_real_answer(self):
        assert sg.parse_groups(REAL_ANSWER, 8) == [[0, 1, 4, 6, 7], [2], [3], [5]]

    @pytest.mark.parametrize("answer", [
        "[[0,1],[2]]",                                   # a bare list
        'Tentu! {"grup": [[0,1],[2]]} Semoga membantu.',  # surrounding text
        '```json\n{"grup": [[0,1],[2]]}\n```',            # fenced
    ])
    def test_the_usual_wrappers(self, answer):
        assert sg.parse_groups(answer, 3) == [[0, 1], [2]]

    @pytest.mark.parametrize("answer", [
        "", None, "tidak ada", '{"grup": "x"}', '{"grup": [[0,1],2]}', '{"grup": [[0,"1"],[2]]}',
        '{"grup": [[0,1],[1,2]]}',                       # an index twice
        '{"grup": [[0],[2]]}',                           # an index missing
        '{"grup": [[0,1],[2],[3]]}',                     # an index that does not exist
        '{"grup": [[true,1],[2]]}',                      # a bool is not an index
        '{"grup": [[0,1],[2]',                           # truncated
    ])
    def test_anything_else_is_refused(self, answer):
        assert sg.parse_groups(answer, 3) is None

    def test_a_bool_is_not_an_index_even_when_it_equals_one(self):
        """True == 1 in Python, so [[0],[true]] would pass an index check done with ==."""
        assert sg.parse_groups('{"grup": [[0],[true]]}', 2) is None
        assert sg.parse_groups('{"grup": [[0],[1]]}', 2) == [[0], [1]]

    def test_empty_groups_are_dropped(self):
        assert sg.parse_groups('{"grup": [[0,1],[],[2]]}', 3) == [[0, 1], [2]]


class TestBuildPrompt:
    def test_numbers_every_cluster_and_shows_at_most_four_headlines_of_90_characters(self):
        long = "x" * 200
        clusters = _clusters([[long, "b", "c", "d", "e-never-shown"]])
        prompt = sg.build_prompt(clusters)
        assert prompt.count("\n0: ") == 1
        assert "x" * 90 in prompt and "x" * 91 not in prompt
        assert "e-never-shown" not in prompt and "d" in prompt.split("0: ")[1]

    def test_asks_for_json_and_for_separate_cases_of_one_institution(self):
        prompt = sg.build_prompt(_clusters())
        assert "Balas HANYA dengan JSON" in prompt and "dua kasus KPK" in prompt


class TestGroupClusters:
    def test_returns_the_groups(self):
        assert sg.group_clusters(FakeSummarizer(), _clusters()) == [[0, 1, 4, 6, 7], [2], [3], [5]]

    def test_one_cluster_needs_no_call(self):
        s = FakeSummarizer()
        assert sg.group_clusters(s, _clusters(SECTION[:1])) == [[0]] and s.prompts == []

    def test_an_unusable_answer_is_a_summarizer_error_that_quotes_it(self):
        with pytest.raises(SummarizerError, match="unusable story grouping"):
            sg.group_clusters(FakeSummarizer("Maaf, saya tidak bisa"), _clusters())

    def test_quota_passes_through(self):
        with pytest.raises(QuotaExhausted):
            sg.group_clusters(FakeSummarizer(QuotaExhausted("429")), _clusters())


class TestPickShown:
    def test_a_story_takes_at_most_its_share_and_the_next_stories_move_up(self):
        ranked = _clusters()
        shown = sg.pick_shown(ranked, [[0, 1, 4, 6, 7], [2], [3], [5]], per_story=2, cap=8)
        assert [ranked.index(c) for c in shown] == [0, 1, 2, 3, 5]              # 4, 6, 7 are the story's 3rd..5th

    def test_the_order_is_kept_and_the_cap_holds(self):
        ranked = _clusters()
        shown = sg.pick_shown(ranked, [[i] for i in range(8)], per_story=2, cap=3)
        assert shown == ranked[:3]

    def test_an_index_the_model_left_out_is_its_own_story(self):
        ranked = _clusters()
        assert sg.pick_shown(ranked, [[0, 1]], per_story=1, cap=8) == [ranked[0]] + ranked[2:]

    def test_zero_means_no_limit(self):
        ranked = _clusters()
        assert sg.pick_shown(ranked, [list(range(8))], per_story=0, cap=8) == ranked


def _article(i, topic, headline):
    return {"sitemap_id": i, "headline": headline, "source": "KOMPAS", "category": "news", "link": f"http://x/{i}",
            "posted_at": 20260928, "topic": topic, "l1_text": f"text {i}"}


class TestGeneratorShowsAStoryAtMostTwice:
    """The generator end to end with a fake summarizer: the section of SECTION's eight clusters."""

    def _generator(self, monkeypatch, summarizer, cap=8):
        ds = MagicMock()
        ds.save_digest.return_value = 1
        gen = ng.NewsletterGenerator(ds, summarizer=summarizer, embed_documents=lambda t: [])
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", cap)
        monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_STORY", 2)
        return gen, ds

    def _run(self, gen, ds, monkeypatch, tmp_path):
        articles, labels = [], []
        for c, group in enumerate(SECTION):
            for k, headline in enumerate(group):
                articles.append(_article(10 * c + k, "law_crime", headline))
                labels.append(c)
        # clusters are ranked by size x sources: give the first cluster the most articles
        monkeypatch.setattr(gen, "_cluster", lambda vectors: list(labels))
        monkeypatch.setattr(gen, "_encode", lambda texts: [[0.0]] * len(texts))
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
        ds.get_articles_for_date.return_value = articles
        return gen.generate(date(2026, 9, 28))

    def test_the_scandal_keeps_two_slots_and_the_other_cases_move_up(self, monkeypatch, tmp_path):
        s = FakeSummarizer()
        gen, ds = self._generator(monkeypatch, s)
        path = self._run(gen, ds, monkeypatch, tmp_path)
        text = open(path, encoding="utf-8").read()
        assert text.count("### ") == 5
        headings = [h for h in text.split("\n") if h.startswith("### ")]
        scandal = [h for h in headings if any(word in h for word in ("Cibinong", "Jimmy Masrin", "Dirjen PAS"))]
        assert len(scandal) == 2, headings
        assert "Remaja Makassar" in text and "Kejagung Tahan" in text and "Kanwil BPN" in text
        assert "dan 3 berita lainnya" in text                     # 8 clusters, 5 shown
        grouping_calls = [p for p in s.prompts if "Balas HANYA dengan JSON" in p]
        assert len(grouping_calls) == 1                           # one call for the section, before the summaries
        assert s.prompts.index(grouping_calls[0]) == 0
        # a cluster that mixes two cases is summarized by the event most of its articles are about
        summary_prompts = [p for p in s.prompts if "Balas HANYA dengan JSON" not in p]
        assert len(summary_prompts) == 5
        assert all("rangkum hanya peristiwa yang paling banyak dibahas" in p for p in summary_prompts)

    def test_the_more_line_counts_hidden_clusters_and_articles_in_no_cluster(self, monkeypatch, tmp_path):
        """DBT-51 (#221): after grouping, 'dan N berita lainnya' is the clusters the story
        cap hid (8 - 5) plus the articles that formed no cluster at all (2)."""
        s = FakeSummarizer()
        gen, ds = self._generator(monkeypatch, s)
        articles, labels = [], []
        for c, group in enumerate(SECTION):
            for k, headline in enumerate(group):
                articles.append(_article(10 * c + k, "law_crime", headline))
                labels.append(c)
        for i, headline in enumerate(["Sidang Perdana Kasus Pungli Terminal", "Polisi Tangkap Pengedar Narkoba"]):
            articles.append(_article(900 + i, "law_crime", headline))
            labels.append(-1)
        monkeypatch.setattr(gen, "_cluster", lambda vectors: list(labels))
        monkeypatch.setattr(gen, "_encode", lambda texts: [[0.0]] * len(texts))
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
        ds.get_articles_for_date.return_value = articles
        text = open(gen.generate(date(2026, 9, 28)), encoding="utf-8").read()
        assert text.count("### ") == 5
        assert "dan 5 berita lainnya" in text

    def test_the_row_and_the_footer_count_the_grouped_sections(self, monkeypatch, tmp_path):
        gen, ds = self._generator(monkeypatch, FakeSummarizer())
        self._run(gen, ds, monkeypatch, tmp_path)
        stats = ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]
        assert (stats["groups_ok"], stats["groups_failed"]) == (1, 0)

    def test_a_failed_grouping_shows_the_ranked_clusters_and_says_so(self, monkeypatch, tmp_path):
        s = FakeSummarizer(group_answer="bukan json")
        gen, ds = self._generator(monkeypatch, s, cap=5)
        path = self._run(gen, ds, monkeypatch, tmp_path)
        text = open(path, encoding="utf-8").read()
        assert text.count("### ") == 5                            # the five best, as before
        assert "pengelompokan cerita gagal di 1 bagian" in text
        assert ds.save_digest.call_args.kwargs["categories"][ng.SUMMARIES_KEY]["groups_failed"] == 1

    def test_quota_while_grouping_stops_every_call(self, monkeypatch, tmp_path, caplog):
        s = FakeSummarizer(group_answer=QuotaExhausted("429", "PerDay"))
        gen, ds = self._generator(monkeypatch, s)
        with caplog.at_level(logging.WARNING, logger=ng.logger.name):
            path = self._run(gen, ds, monkeypatch, tmp_path)
        assert len(s.prompts) == 1                                # the grouping call was the only call
        assert "kuota harian habis" in open(path, encoding="utf-8").read()
        assert any("while grouping stories" in r.message for r in caplog.records)

    def test_zero_turns_the_grouping_off(self, monkeypatch, tmp_path):
        s = FakeSummarizer()
        gen, ds = self._generator(monkeypatch, s)
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_STORY", 0)
        self._run(gen, ds, monkeypatch, tmp_path)
        assert not [p for p in s.prompts if "Balas HANYA dengan JSON" in p]

    def test_consecutive_grouping_failures_stop_the_calls(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS", 1)
        s = FakeSummarizer(group_answer=SummarizerError("down"))
        gen, ds = self._generator(monkeypatch, s)
        path = self._run(gen, ds, monkeypatch, tmp_path)
        assert len(s.prompts) == 1 and "layanan gagal berulang" in open(path, encoding="utf-8").read()

    def test_a_section_with_no_more_clusters_than_one_story_may_take_needs_no_call(self, monkeypatch, tmp_path):
        s = FakeSummarizer()
        gen, ds = self._generator(monkeypatch, s)
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_STORY", 8)
        self._run(gen, ds, monkeypatch, tmp_path)
        assert not [p for p in s.prompts if "Balas HANYA dengan JSON" in p]

    def test_the_raw_answer_never_reaches_the_digest(self, monkeypatch, tmp_path):
        gen, ds = self._generator(monkeypatch, FakeSummarizer())
        text = open(self._run(gen, ds, monkeypatch, tmp_path), encoding="utf-8").read()
        assert json.dumps(REAL_ANSWER)[1:20] not in text and "grup" not in text
