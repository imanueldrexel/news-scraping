"""SYS-65 (#211): clusters are built per topic, so a story whose articles the
probe tagged with different topics used to be shown in two sections. After the
per-topic clustering, clusters of any topics that are within
NEWSLETTER_CLUSTER_DISTANCE of each other (average member-to-member cosine
distance) are merged into the section of the larger one.

Vectors here are unit vectors at an angle, so the cosine distance between two
of them is 1 - cos(angle difference) and the tests control it exactly."""
import math
from unittest.mock import MagicMock

import pytest

import newscrawler.core.newsletter_generator as ng

T = 0.30


def _vec(deg):
    return [math.cos(math.radians(deg)), math.sin(math.radians(deg))]


def _art(i, topic, deg, cluster, source="KOMPAS"):
    return {"sitemap_id": i, "headline": f"h{i}", "source": source, "category": "news", "link": f"http://x/{i}",
            "posted_at": 20260928, "topic": topic, "l1_text": f"t{i}", "_cluster": cluster, "_deg": deg}


@pytest.fixture
def gen(monkeypatch):
    g = ng.NewsletterGenerator(MagicMock(), summarizer=None, embed_documents=lambda t: [[0.0, 1.0]] * len(t))
    monkeypatch.setattr(ng, "NEWSLETTER_CLUSTER_DISTANCE", T)
    monkeypatch.setattr(ng, "NEWSLETTER_MIN_CLUSTER_SIZE", 2)
    monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", 8)
    # The per-topic clusterer is stubbed: the third coordinate of each vector is the article's
    # own cluster label (-1 = unclustered).
    monkeypatch.setattr(g, "_cluster", lambda vectors: [int(v[2]) for v in vectors])
    return g


def _sections(gen, arts):
    vectors = [_vec(a["_deg"]) + [-1 if a["_cluster"] is None else a["_cluster"]] for a in arts]
    original = gen._merge_across_sections
    # the merge pass must see geometry only, not the stub label
    gen._merge_across_sections = lambda entries, vecs: original(entries, [v[:2] for v in vecs])
    return gen.build_sections(arts, vectors)


def _ids(section):
    return [sorted(a["sitemap_id"] for a in c["articles"]) for c in section["clusters"]]


def _by_topic(sections):
    return {s["topic"]: s for s in sections}


class TestOneStoryTwoTopics:
    def test_a_story_tagged_with_two_topics_is_shown_once(self, gen):
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 2, 0), _art(3, "consumer", 4, 0),
                _art(4, "politics_government", 1, 0), _art(5, "politics_government", 3, 0)]
        sections = _by_topic(_sections(gen, arts))
        assert list(sections) == ["consumer"], "the smaller cluster's section is left with nothing"
        assert _ids(sections["consumer"]) == [[1, 2, 3, 4, 5]]
        assert sections["consumer"]["article_count"] == 5

    def test_on_a_tie_the_earlier_section_wins(self, gen):
        arts = [_art(1, "law_crime", 0, 0), _art(2, "law_crime", 1, 0),
                _art(3, "markets", 2, 0), _art(4, "markets", 3, 0)]
        assert list(_by_topic(_sections(gen, arts))) == ["markets"]

    def test_the_larger_cluster_keeps_its_section_whatever_the_order(self, gen):
        arts = [_art(1, "markets", 0, 0), _art(2, "markets", 1, 0),
                _art(3, "law_crime", 2, 0), _art(4, "law_crime", 3, 0), _art(5, "law_crime", 4, 0)]
        assert list(_by_topic(_sections(gen, arts))) == ["law_crime"]

    def test_the_merged_cluster_describes_all_its_articles(self, gen):
        arts = [_art(1, "consumer", 0, 0, "DETIK"), _art(2, "consumer", 2, 0, "DETIK"),
                _art(3, "consumer", 3, 0, "DETIK"),
                _art(4, "politics_government", 1, 0, "KONTAN"), _art(5, "politics_government", 4, 0, "BISNIS")]
        (section,) = _sections(gen, arts)
        cluster = section["clusters"][0]
        assert set(cluster["sources"]) == {"DETIK", "KONTAN", "BISNIS"}
        assert cluster["headline"] == "h5", "the most authoritative source's headline, from the merged articles"
        assert section["ranked"][0] is cluster


class TestWhatIsNotMerged:
    def test_different_stories_in_different_topics_stay_apart(self, gen):
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 2, 0),
                _art(3, "law_crime", 90, 0), _art(4, "law_crime", 92, 0)]
        assert set(_by_topic(_sections(gen, arts))) == {"consumer", "law_crime"}

    def test_the_cut_is_the_clustering_distance(self, gen):
        # cos(46 deg) = 0.695 -> distance 0.305 > 0.30; cos(45 deg) = 0.707 -> 0.293 <= 0.30
        far = [_art(1, "consumer", 0, 0), _art(2, "consumer", 0, 0),
               _art(3, "law_crime", 46, 0), _art(4, "law_crime", 46, 0)]
        near = [_art(1, "consumer", 0, 0), _art(2, "consumer", 0, 0),
                _art(3, "law_crime", 45, 0), _art(4, "law_crime", 45, 0)]
        assert len(_sections(gen, far)) == 2
        assert len(_sections(gen, near)) == 1

    def test_linkage_is_average_not_single(self, gen):
        """One close member must not merge two clusters that are far on average."""
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 0, 0), _art(3, "consumer", 0, 0),
                _art(4, "law_crime", 30, 0), _art(5, "law_crime", 80, 0), _art(6, "law_crime", 80, 0)]
        # member 4 is 30 deg (distance 0.134) from the first cluster; the cluster average is
        # (0.134 + 2 * 0.826) / 3 = 0.595 > 0.30
        assert len(_sections(gen, arts)) == 2

    def test_unclustered_articles_stay_in_their_own_topic(self, gen):
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 1, 0), _art(3, "consumer", 2, 0),
                _art(4, "law_crime", 1, 0), _art(5, "law_crime", 2, 0), _art(6, "law_crime", 3, None)]
        sections = _by_topic(_sections(gen, arts))
        assert set(sections) == {"consumer", "law_crime"}
        law = sections["law_crime"]
        assert law["clusters"] == [] and law["unclustered"] == 1 and law["article_count"] == 1
        assert law["more"] == 1
        assert sections["consumer"]["article_count"] == 5

    def test_no_articles_and_one_cluster_need_no_pass(self, gen):
        assert _sections(gen, []) == []
        (section,) = _sections(gen, [_art(1, "consumer", 0, 0), _art(2, "consumer", 1, 0)])
        assert _ids(section) == [[1, 2]]


class TestCounts:
    def test_more_is_recounted_after_the_merge(self, gen, monkeypatch):
        monkeypatch.setattr(ng, "NEWSLETTER_MAX_CLUSTERS_PER_TOPIC", 1)
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 1, 0), _art(3, "consumer", 2, 0),
                _art(4, "consumer", 100, 1), _art(5, "consumer", 101, 1),   # a second consumer story
                _art(6, "law_crime", 1, 0), _art(7, "law_crime", 2, 0)]     # the first story again
        sections = _by_topic(_sections(gen, arts))
        consumer = sections["consumer"]
        assert "law_crime" not in sections
        assert consumer["cluster_count"] == 2 and len(consumer["clusters"]) == 1
        assert consumer["more"] == 1
        assert consumer["article_count"] == 7

    def test_every_article_is_in_exactly_one_place(self, gen):
        arts = [_art(1, "consumer", 0, 0), _art(2, "consumer", 1, 0),
                _art(3, "law_crime", 1, 0), _art(4, "law_crime", 2, 0), _art(5, "law_crime", 200, None),
                _art(6, "markets", 90, 0), _art(7, "markets", 91, 0)]
        sections = _sections(gen, arts)
        in_clusters = [a["sitemap_id"] for s in sections for c in s["ranked"] for a in c["articles"]]
        assert len(in_clusters) == len(set(in_clusters)) == 6
        assert sum(s["unclustered"] for s in sections) == 1
        assert sum(s["article_count"] for s in sections) == 7
