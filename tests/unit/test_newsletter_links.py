"""SYS-69 (#217): a cluster's "Artikel terkait" links are one per outlet (best
outlets first), never the same outlet three times while other outlets covered
the story, and each link is labelled with its headline, not the digest date."""
from datetime import date
from unittest.mock import MagicMock

import newscrawler.core.newsletter_generator as ng


def _a(i, source, headline=None, link="auto"):
    return {"sitemap_id": i, "headline": headline or f"headline {i}", "source": source,
            "link": f"http://x/{i}" if link == "auto" else link}


def _sources(links):
    return [l["source"] for l in links]


class TestTopLinks:
    def test_three_articles_of_one_outlet_do_not_crowd_out_the_others(self):
        arts = [_a(1, "KONTAN"), _a(2, "KONTAN"), _a(3, "KONTAN"), _a(4, "KOMPAS"), _a(5, "DETIK")]
        assert _sources(ng.NewsletterGenerator._top_links(arts)) == ["KONTAN", "KOMPAS", "DETIK"]

    def test_outlets_are_ranked_by_authority(self):
        arts = [_a(1, "DETIK"), _a(2, "KOMPAS"), _a(3, "BISNIS"), _a(4, "TEMPO")]
        assert _sources(ng.NewsletterGenerator._top_links(arts)) == ["BISNIS", "KOMPAS", "TEMPO"]

    def test_the_outlet_is_matched_case_insensitively(self):
        arts = [_a(1, "Kontan"), _a(2, "KONTAN"), _a(3, "kontan"), _a(4, "Detik")]
        assert _sources(ng.NewsletterGenerator._top_links(arts)) == ["Kontan", "Detik", "KONTAN"]

    def test_a_story_with_two_outlets_fills_the_third_slot_with_the_best_outlet(self):
        arts = [_a(1, "KONTAN"), _a(2, "KONTAN"), _a(3, "DETIK")]
        links = ng.NewsletterGenerator._top_links(arts)
        assert _sources(links) == ["KONTAN", "DETIK", "KONTAN"]
        assert len({l["link"] for l in links}) == 3

    def test_a_single_outlet_story_still_gets_its_three_links(self):
        arts = [_a(i, "KONTAN") for i in range(5)]
        assert len(ng.NewsletterGenerator._top_links(arts)) == 3

    def test_an_article_without_a_link_takes_no_slot(self):
        arts = [_a(1, "BISNIS", link=""), _a(2, "KONTAN"), _a(3, "KOMPAS")]
        links = ng.NewsletterGenerator._top_links(arts)
        assert _sources(links) == ["KONTAN", "KOMPAS"]

    def test_at_most_three_links(self):
        arts = [_a(i, f"OUTLET{i}") for i in range(10)]
        assert len(ng.NewsletterGenerator._top_links(arts)) == 3


class TestLinkLabel:
    def test_a_label_is_source_and_headline(self):
        link = {"source": "KONTAN", "headline": "Rupiah menguat"}
        assert ng.NewsletterGenerator._link_label(link) == "KONTAN: Rupiah menguat"

    def test_a_long_headline_is_cut_at_a_word(self):
        link = {"source": "KONTAN", "headline": "kata " * 40}
        label = ng.NewsletterGenerator._link_label(link)
        assert label.endswith("kata…") and len(label) <= len("KONTAN: ") + ng._LINK_LABEL_CHARS + 1

    def test_brackets_in_a_headline_cannot_break_the_markdown_link(self):
        link = {"source": "KONTAN", "headline": "[Update] IHSG [naik]"}
        label = ng.NewsletterGenerator._link_label(link)
        assert "[" not in label and "]" not in label

    def test_an_empty_headline_leaves_the_source(self):
        assert ng.NewsletterGenerator._link_label({"source": "KONTAN", "headline": "  "}) == "KONTAN"


class TestRendered:
    def test_the_digest_links_use_headlines_not_the_date(self, monkeypatch):
        gen = ng.NewsletterGenerator(MagicMock(), summarizer=None, embed_documents=lambda t: [[0.0]] * len(t))
        arts = [_a(1, "KONTAN", "Rupiah menguat"), _a(2, "KONTAN", "Rupiah naik tipis"), _a(3, "DETIK", "Kurs hari ini")]
        section = {"topic": "markets", "article_count": 3, "cluster_count": 1, "more": 0,
                   "clusters": [gen._describe_cluster(arts)]}
        md = gen._render_markdown(date(2026, 9, 28), [section], arts)
        line = next(l for l in md.splitlines() if l.startswith("**Artikel terkait:**"))
        assert line.count("](http") == 3
        assert "[KONTAN: Rupiah menguat](http://x/1)" in line
        assert "28 September 2026" not in line
