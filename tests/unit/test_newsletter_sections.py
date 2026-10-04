"""SYS-40 (#126): the digest is sectioned by articles.topic, finance first, with
at most NEWSLETTER_MAX_CLUSTERS_PER_TOPIC clusters per section and one "and N
more" line for the rest. Offline: stub topics, stub vectors, a stub clusterer."""
from datetime import date
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_generator as ng
from newscrawler.core.filter_rubric import TOPICS_FINANCE, TOPICS_NEWS


def _art(i, topic, source="KOMPAS", cluster=None):
    return {"sitemap_id": i, "headline": f"h{i}", "source": source, "category": "news",
            "link": f"http://x/{i}", "posted_at": 20260929, "topic": topic,
            "l1_text": f"text {i}", "_cluster": cluster}


def _gen(monkeypatch, cap=2):
    ds = MagicMock()
    gen = ng.NewsletterGenerator(ds, summarizer=None, embed_documents=lambda texts: [[0.0, 1.0]] * len(texts))
    monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", cap)
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    return gen, ds


def _sections(gen, monkeypatch, articles):
    """Each article's stub vector carries its cluster label (-1 = noise), and
    the stub clusterer reads it back."""
    monkeypatch.setattr(gen, "_cluster", lambda vectors: [int(v[0]) for v in vectors])
    vectors = [[-1 if a["_cluster"] is None else a["_cluster"]] for a in articles]
    return gen.build_sections(articles, vectors)


class TestSections:
    def test_finance_sections_come_first_in_rubric_order(self, monkeypatch):
        gen, _ = _gen(monkeypatch)
        arts = [_art(1, "law_crime", cluster=0), _art(2, "law_crime", cluster=0),
                _art(3, "markets", cluster=0), _art(4, "markets", cluster=0),
                _art(5, "politics_government"), _art(6, "consumer")]
        order = [s["topic"] for s in _sections(gen, monkeypatch, arts)]
        assert order == ["markets", "consumer", "politics_government", "law_crime"]
        assert ng.SECTION_ORDER == TOPICS_FINANCE + TOPICS_NEWS

    def test_no_section_exceeds_the_cap_and_the_rest_is_counted(self, monkeypatch):
        gen, _ = _gen(monkeypatch, cap=2)
        arts = []
        for c in range(4):                       # four 2-article clusters in one topic
            arts += [_art(10 * c + 1, "markets", cluster=c), _art(10 * c + 2, "markets", cluster=c)]
        arts += [_art(99, "markets")]            # one unclustered story
        (sec,) = _sections(gen, monkeypatch, arts)
        assert len(sec["clusters"]) == 2 and sec["cluster_count"] == 4
        assert sec["more"] == 2 + 1

    def test_clusters_rank_by_size_times_sources(self, monkeypatch):
        gen, _ = _gen(monkeypatch, cap=1)
        arts = [_art(1, "markets", "KOMPAS", 0), _art(2, "markets", "KOMPAS", 0), _art(3, "markets", "KOMPAS", 0),
                _art(4, "markets", "KOMPAS", 1), _art(5, "markets", "DETIK", 1)]
        (sec,) = _sections(gen, monkeypatch, arts)
        # cluster 0: 3 articles x 1 source = 3; cluster 1: 2 x 2 = 4
        assert {a["sitemap_id"] for a in sec["clusters"][0]["articles"]} == {4, 5}

    def test_an_article_without_a_known_topic_goes_to_other_news(self, monkeypatch):
        gen, _ = _gen(monkeypatch)
        (sec,) = _sections(gen, monkeypatch, [_art(1, None), _art(2, "soft"), _art(3, "cooking")])
        assert sec["topic"] == "other_news" and sec["article_count"] == 3


class TestGenerate:
    def test_render_order_cap_and_the_digest_row(self, monkeypatch, tmp_path):
        gen, ds = _gen(monkeypatch, cap=1)
        monkeypatch.setattr(ng, "DIGESTS_DIR", str(tmp_path))
        arts = [_art(1, "law_crime", cluster=0), _art(2, "law_crime", cluster=0),
                _art(3, "markets", cluster=0), _art(4, "markets", cluster=0),
                _art(5, "markets", cluster=1), _art(6, "markets", cluster=1)]
        ds.get_articles_for_date.return_value = arts
        labels = iter([[0, 0, 1, 1], [0, 0]])  # markets first, then law_crime
        monkeypatch.setattr(gen, "_cluster", lambda vectors: next(labels))

        path = gen.generate(date(2026, 9, 29))

        md = open(path, encoding="utf-8").read()
        assert md.index(ng.SECTION_TITLES["markets"]) < md.index(ng.SECTION_TITLES["law_crime"])
        assert md.count("### ") == 2, "one shown cluster per section at cap=1"
        assert "dan 1 berita lainnya" in md
        kwargs = ds.save_digest.call_args.kwargs
        topics = {k: v for k, v in kwargs["categories"].items() if not k.startswith("_")}
        assert topics == {"markets": {"articles": 4, "clusters": 2, "shown": 1},
                          "law_crime": {"articles": 2, "clusters": 1, "shown": 1}}
        assert kwargs["categories"][ng.SUMMARIES_KEY]["total"] == 2          # SYS-68: counted beside the topics
        assert kwargs["cluster_count"] == 3 and kwargs["article_count"] == 6

    def test_the_keyword_category_is_gone(self):
        assert not hasattr(ng.NewsletterGenerator, "assign_category")
        import newscrawler.core.constants as c
        assert not hasattr(c, "NEWSLETTER_CATEGORY_KEYWORDS")


class TestClustering:
    def test_a_chain_of_near_neighbours_is_not_one_story(self):
        """DBSCAN joined a chain in which each neighbour is close to the next;
        average linkage keeps two tight groups apart even with a bridge."""
        import numpy as np
        gen = ng.NewsletterGenerator(MagicMock(), summarizer=None, embed_documents=lambda t: [])
        a = [np.array([1.0, 0.0, 0.0])] * 4
        b = [np.array([0.0, 1.0, 0.0])] * 4
        bridge = [np.array([0.7, 0.7, 0.0])]
        labels = gen._cluster(np.vstack(a + bridge + b))
        assert labels[0] == labels[3] and labels[5] == labels[8]
        assert labels[0] != labels[5]

    def test_a_group_below_the_minimum_size_is_unclustered(self, monkeypatch):
        import numpy as np
        monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
        gen = ng.NewsletterGenerator(MagicMock(), summarizer=None, embed_documents=lambda t: [])
        labels = gen._cluster(np.array([[1.0, 0.0], [1.0, 0.01], [0.0, 1.0]]))
        assert labels[0] == labels[1] != -1 and labels[2] == -1
