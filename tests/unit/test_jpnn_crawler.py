"""SRC-41 (#135): JPNNCrawler._get_branches's re.sub matched only the www host,
so every regional-subdomain entry (bali, banten, jabar, ... 15 of them) came
back unchanged and became a branch keyed by its own URL -- 78 of 90 live
branches on 2026-09-20, 6,104 sitemaps.category rows. Fourth instance of the
SRC-14 (IDNTIMES) / SRC-33 (VIVA) / SRC-36 (CNN) shape.

The regional host is part of the key (`bali/politik`): fifteen hosts each
publish a `politik` leaf, and a dict keyed on the section alone would keep one
and silently drop fourteen.
"""
from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers.jpnn.jpnn_crawler import JPNNCrawler

_INDEX_ENTRIES = (
    "https://www.jpnn.com/sitemap_post_nasional.xml",
    "https://www.jpnn.com/sitemap_posturl_nasional.xml",
    "https://www.jpnn.com/sitemap_postimg_nasional.xml",
    "https://www.jpnn.com/sitemap_post_politik.xml",
    "https://www.jpnn.com/sitemap_post_olahraga.xml",
    "https://bali.jpnn.com/sitemap_post_bali-terkini.xml",
    "https://bali.jpnn.com/sitemap_post_politik.xml",
    "https://bali.jpnn.com/sitemap_post_sport.xml",
    "https://jogja.jpnn.com/sitemap_post_politik.xml",
    "https://jogja.jpnn.com/sitemap_posturl_politik.xml",
)


def _index(entries=_INDEX_ENTRIES):
    body = "".join(f"<sitemap><loc>{e}</loc></sitemap>" for e in entries)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'
    return BeautifulSoup(xml, "xml")


class TestJpnnGetBranches:
    def test_www_sections_keep_their_bare_name(self):
        branches = JPNNCrawler._get_branches(_index())
        assert branches["nasional"] == "https://www.jpnn.com/sitemap_post_nasional.xml"
        assert branches["politik"] == "https://www.jpnn.com/sitemap_post_politik.xml"
        assert branches["olahraga"] == "https://www.jpnn.com/sitemap_post_olahraga.xml"

    def test_regional_sections_are_keyed_host_slash_section(self):
        branches = JPNNCrawler._get_branches(_index())
        assert branches["bali/bali-terkini"] == "https://bali.jpnn.com/sitemap_post_bali-terkini.xml"
        assert branches["bali/politik"] == "https://bali.jpnn.com/sitemap_post_politik.xml"
        assert branches["bali/sport"] == "https://bali.jpnn.com/sitemap_post_sport.xml"
        assert branches["jogja/politik"] == "https://jogja.jpnn.com/sitemap_post_politik.xml"

    def test_same_section_on_two_hosts_does_not_collapse(self):
        branches = JPNNCrawler._get_branches(_index())
        politik = {k: v for k, v in branches.items() if k.endswith("politik")}
        assert len(politik) == 3, politik

    def test_no_key_is_ever_a_url(self):
        branches = JPNNCrawler._get_branches(_index())
        assert not any(k.startswith("http") for k in branches), list(branches)

    def test_posturl_and_postimg_twins_are_not_branches(self):
        branches = JPNNCrawler._get_branches(_index())
        assert not any("posturl" in v or "postimg" in v for v in branches.values())
        assert len(branches) == 7

    def test_unnameable_loc_is_skipped_not_keyed(self):
        branches = JPNNCrawler._get_branches(_index([
            "https://www.jpnn.com/sitemap.xml",
            "https://www.jpnn.com/sitemap_post_nasional/extra.xml",
            "https://example.com/sitemap_post_nasional.xml",
        ]))
        assert branches == {}


class TestJpnnBranchNameFromUrl:
    """The one decision `_get_branches` and the category repair script share."""

    def test_www(self):
        assert JPNNCrawler.branch_name_from_url("https://www.jpnn.com/sitemap_post_kriminal.xml") == "kriminal"

    def test_regional(self):
        assert JPNNCrawler.branch_name_from_url("https://kalsel.jpnn.com/sitemap_post_kriminal.xml") == "kalsel/kriminal"

    def test_not_a_post_leaf(self):
        assert JPNNCrawler.branch_name_from_url("https://www.jpnn.com/sitemap_posturl_kriminal.xml") is None
