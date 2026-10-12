"""SRC-59 (#260): investor.id's sitemap_news.xml answers 404 since the 2026-10-06 19:00 run, and
INVESTORID saved nothing. Its index (sitemap.xml) still lists the dead news sitemap next to the live
sitemap_post.xml, which holds the latest 100 articles, lastmod only (the base crawler's SYS-32 path).

Fixture: the live index of 2026-10-12 ~21:10 WIB (fetched with the browser UA that BROWSER_UA_HOSTS
gives investor.id)."""
from bs4 import BeautifulSoup

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.scrapers.investor_id.investorid_crawler import InvestorIDCrawler

LIVE_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://investor.id/sitemap_basic.xml</loc></sitemap>
  <sitemap><loc>https://investor.id/sitemap_post.xml</loc></sitemap>
  <sitemap><loc>https://investor.id/sitemap_news.xml</loc></sitemap>
</sitemapindex>"""


def _soup(xml):
    return BeautifulSoup(xml, "xml")


class TestInvestorIdBranches:
    def test_the_source_reads_the_index(self):
        assert URL.INVESTORID.value == "https://investor.id/sitemap.xml"

    def test_the_live_index_gives_the_post_sitemap_keyed_news(self):
        """`news` as the old leaf was keyed, so the stored category does not change."""
        assert InvestorIDCrawler._get_branches(_soup(LIVE_INDEX)) == {"news": "https://investor.id/sitemap_post.xml"}

    def test_the_dead_news_sitemap_and_the_basic_one_are_never_branches(self):
        index = LIVE_INDEX.replace("<sitemap><loc>https://investor.id/sitemap_post.xml</loc></sitemap>", "")
        assert InvestorIDCrawler._get_branches(_soup(index)) == {}

    def test_a_lookalike_url_is_not_the_post_sitemap(self):
        index = LIVE_INDEX.replace("https://investor.id/sitemap_post.xml", "https://investor.id/sitemap_post.xml.bak")
        assert InvestorIDCrawler._get_branches(_soup(index)) == {}

    def test_no_branch_is_keyed_by_a_url(self):
        assert all("://" not in key for key in InvestorIDCrawler._get_branches(_soup(LIVE_INDEX)))

    def test_the_dots_are_literal(self):
        index = LIVE_INDEX.replace("https://investor.id/sitemap_post.xml", "https://investorXid/sitemap_postXxml")
        assert InvestorIDCrawler._get_branches(_soup(index)) == {}


class TestInvestorIdPlaceholderHeadline:
    """SRC-59: the post sitemap is lastmod-only, so a row starts with the slug as its headline. The
    id is a path segment before the slug, not the slug's tail, so the base test (SYS-33) never saw a
    placeholder and "Medcoenergi Akuisisi 10 Hak Partisipasi Eni" stayed the title instead of the
    page's "MedcoEnergi Akuisisi 10% Hak Partisipasi Eni" (live, 2026-10-12)."""

    LINK = "https://investor.id/business/457702/medcoenergi-akuisisi-10-hak-partisipasi-eni?page=all"

    def _dto(self, headline, link=LINK):
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        return SitemapDTO(headline=headline, link=link, sources="INVESTORID", category="business")

    def test_the_slug_headline_is_a_placeholder(self):
        slug = InvestorIDCrawler._derive_headline_from_url(self.LINK)
        assert slug == "Medcoenergi Akuisisi 10 Hak Partisipasi Eni"
        assert InvestorIDCrawler._is_placeholder_headline(self._dto(slug))

    def test_a_real_headline_is_not(self):
        assert not InvestorIDCrawler._is_placeholder_headline(self._dto("MedcoEnergi Akuisisi 10% Hak Partisipasi Eni"))

    def test_a_link_without_the_id_segment_is_not(self):
        link = "https://investor.id/business/medcoenergi-akuisisi-10-hak-partisipasi-eni"
        slug = InvestorIDCrawler._derive_headline_from_url(link)
        assert not InvestorIDCrawler._is_placeholder_headline(self._dto(slug, link))

    def test_the_base_rule_is_unchanged_for_other_sources(self):
        """KOMPAS-style `/<id>/<slug>`: a genuine slug-equal headline stays genuine."""
        from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        link = "https://nasional.kompas.com/read/2026/10/12/09453441/keadilan-terkubur-longsor"
        dto = SitemapDTO(headline="Keadilan Terkubur Longsor", link=link, sources="KOMPAS")
        assert not Crawler._is_placeholder_headline(dto)

    def test_the_page_title_replaces_the_placeholder_with_one_space_per_gap(self):
        from bs4 import BeautifulSoup
        html = ('<html><head><meta property="og:title" content="Resmi Beroperasi, Universitas Ciputra '
                'Menambah&nbsp; Lengkap New CBD Puri"></head></html>')
        assert InvestorIDCrawler._get_page_title(BeautifulSoup(html, "html.parser")) == \
            "Resmi Beroperasi, Universitas Ciputra Menambah Lengkap New CBD Puri"
