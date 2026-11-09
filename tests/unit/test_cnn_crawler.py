"""SRC-36 (#129): CNNCrawler._get_branches's regex expected two path segments
before sitemap_news.xml; the live index has one. re.sub on a non-matching link
returns the input unchanged, so every branch -- and every sitemaps.category for
CNN, 682 rows -- was the full sitemap URL, and the exact-match half of the
SYS-31 category deny-list (gaya-hidup) could not see it: 5 lifestyle articles
saved. Third instance of the SRC-14 (IDNTIMES) / SRC-33 (VIVA) shape.

Fixture is the live index shape on 2026-09-20 (9 sections x news/web/video
leaves, a tv/ video-only entry) plus the two shapes the ticket names: a
`longform` entry and a two-segment entry -- neither may become a branch, and
no key may ever be a URL.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.cnn.cnn_crawler import CNNCrawler

_LIVE_SECTIONS = (
    "nasional", "internasional", "ekonomi", "olahraga", "teknologi",
    "otomotif", "edukasi", "hiburan", "gaya-hidup",
)


def _index(extra_entries=()):
    entries = []
    for section in _LIVE_SECTIONS:
        for leaf in ("sitemap_news.xml", "sitemap_web.xml", "sitemap_video.xml"):
            entries.append(f"https://www.cnnindonesia.com/{section}/{leaf}")
    entries.append("https://www.cnnindonesia.com/tv/sitemap_video.xml")
    entries.extend(extra_entries)
    body = "".join(f"<sitemap><loc>{e}</loc></sitemap>" for e in entries)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'
    return BeautifulSoup(xml, "xml")


class TestCnnGetBranches:
    def test_live_index_yields_exactly_the_nine_section_names(self):
        branches = CNNCrawler._get_branches(_index())
        assert branches == {
            s: f"https://www.cnnindonesia.com/{s}/sitemap_news.xml" for s in _LIVE_SECTIONS
        }

    def test_no_key_is_ever_a_url(self):
        branches = CNNCrawler._get_branches(_index([
            "https://www.cnnindonesia.com/longform/sitemap_news.xml",
            "https://www.cnnindonesia.com/nasional/politik/sitemap_news.xml",
            "https://www.cnnindonesia.com/sitemap_news.xml",
            "https://cnnindonesia.com/nasional/sitemap_news.xml",
        ]))
        assert not any(k.startswith("http") for k in branches), list(branches)
        assert not any("/" in k for k in branches), list(branches)

    def test_two_segment_entry_is_skipped_not_keyed(self):
        # The old regex only ever matched this shape; the live index never
        # had it. A <loc> the crawler cannot name is skipped, never keyed.
        branches = CNNCrawler._get_branches(_index([
            "https://www.cnnindonesia.com/nasional/politik/sitemap_news.xml",
        ]))
        assert "politik" not in branches
        assert "nasional/politik" not in branches
        assert len(branches) == len(_LIVE_SECTIONS)

    def test_longform_stays_excluded_and_the_nine_are_unchanged(self):
        # The pre-SRC-36 code excluded "longform" by substring; it is not in
        # the live index and has never been sampled, so the exclusion is
        # carried over unchanged (the ticket's expected set is exactly the
        # nine even with this entry present).
        branches = CNNCrawler._get_branches(_index([
            "https://www.cnnindonesia.com/longform/sitemap_news.xml",
        ]))
        assert "longform" not in branches
        assert set(branches) == set(_LIVE_SECTIONS)

    def test_web_and_video_twins_and_tv_are_not_branches(self):
        branches = CNNCrawler._get_branches(_index())
        assert "tv" not in branches
        assert not any("sitemap_web" in v or "sitemap_video" in v for v in branches.values())

    def test_empty_index_yields_no_branches(self):
        soup = BeautifulSoup(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>', "xml"
        )
        assert CNNCrawler._get_branches(soup) == {}


class TestCnnBranchNameFromUrl:
    """The one decision `_get_branches` and the category repair script share."""

    def test_news_leaf(self):
        assert CNNCrawler.branch_name_from_url("https://www.cnnindonesia.com/gaya-hidup/sitemap_news.xml") == "gaya-hidup"

    def test_web_twin_is_unnameable(self):
        assert CNNCrawler.branch_name_from_url("https://www.cnnindonesia.com/gaya-hidup/sitemap_web.xml") is None

    def test_two_segments_is_unnameable(self):
        assert CNNCrawler.branch_name_from_url("https://www.cnnindonesia.com/nasional/politik/sitemap_news.xml") is None
