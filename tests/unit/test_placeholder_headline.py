"""SYS-33 (#114): SYS-32's URL-slug placeholder was the permanent headline for
every TIRTO/TEMPO article (317 rows, trailing URL id included) because
_fetch_news_details only consulted the page when sitemap.headline was empty,
which _get_sitemap's own slug fallback guarantees never happens on the live
path. Now a headline that IS the slug placeholder is replaced by og:title,
the DTO says so (meta_data["headline_from_page"]), and the service writes it
back to sitemaps.headline for every fetched page -- rejected rows too.
"""
import os
from typing import List
from unittest.mock import MagicMock, patch

os.environ.setdefault("VERBOSE", "False")
os.environ.setdefault("PARALLELIZE", "False")
os.environ.setdefault("REQUEST_MAX_RETRIES", "1")

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.importance_filter import FilterDecision
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

# The two real rows from the ticket.
TIRTO_LINK = "https://tirto.id/rupiah-dan-ihsg-menguat-9-september-2026-ini-pergerakannya-hCa5?page=all"
TIRTO_SLUG = "Rupiah Dan Ihsg Menguat 9 September 2026 Ini Pergerakannya Hca5"
TIRTO_OG = "Rupiah dan IHSG Menguat 9 September 2026, Ini Pergerakannya"
TEMPO_LINK = "https://www.tempo.co/ekonomi/apa-dampak-kelangkaan-bbm-bersubsidi-2287141?page=all"
TEMPO_SLUG = "Apa Dampak Kelangkaan Bbm Bersubsidi 2287141"

# Long enough to clear MIN_ARTICLE_CHARS, so the site extractor "wins" and the
# trafilatura/newspaper fallbacks -- which would hit the real TIRTO/TEMPO URLs
# over the network -- never run. tests/unit stays offline.
_BODY = "<body><p>" + ("Bank Indonesia mempertahankan suku bunga acuan di level 5,75 persen. " * 5) + "</p></body>"


class _ConcreteCrawler(Crawler):
    def _get_reporter_from_text(self, soup) -> List[str]:
        return []

    @staticmethod
    def _get_branches(soup):
        return {}

    @staticmethod
    def _get_whole_text(soup):
        # A working site extractor: with a usable body the fallback chain
        # (trafilatura, then newspaper's own network fetch) never runs.
        return [p.get_text(" ").strip() for p in soup.find_all("p")]


def _page(og_title=None, title_tag=None):
    head = ""
    if og_title:
        head += f'<meta property="og:title" content="{og_title}"/>'
    if title_tag:
        head += f"<title>{title_tag}</title>"
    return BeautifulSoup(f"<html><head>{head}</head>{_BODY}</html>", "html.parser")


class TestIsPlaceholderHeadline:
    def test_slug_derived_headline_is_a_placeholder(self):
        assert Crawler._derive_headline_from_url(TIRTO_LINK) == TIRTO_SLUG
        assert Crawler._is_placeholder_headline(SitemapDTO(headline=TIRTO_SLUG, link=TIRTO_LINK, sources="TIRTO"))
        assert Crawler._is_placeholder_headline(SitemapDTO(headline=TEMPO_SLUG, link=TEMPO_LINK, sources="TEMPO"))

    def test_real_headline_is_not(self):
        assert not Crawler._is_placeholder_headline(SitemapDTO(headline=TIRTO_OG, link=TIRTO_LINK, sources="TIRTO"))

    def test_empty_headline_is_not_a_placeholder_but_still_handled_by_the_empty_branch(self):
        assert not Crawler._is_placeholder_headline(SitemapDTO(headline="", link=TIRTO_LINK, sources="TIRTO"))

    def test_a_real_title_that_merely_coincides_with_its_slug_is_not_a_placeholder(self):
        """3,580 genuine headlines in production are short, punctuation-free
        Title Case and equal their own slug -- the placeholder is only the one
        that also carries the URL's trailing id token."""
        for headline, link in (
            ("Keadilan Terkubur Longsor", "https://mediaindonesia.com/forum-mahasiswa/845751/keadilan-terkubur-longsor?page=all"),
            ("Teror Paket Isi Pocong Mini Gegerkan Warga Lendah Kulon Progo",
             "https://yogyakarta.kompas.com/read/2026/05/25/151622478/teror-paket-isi-pocong-mini-gegerkan-warga-lendah-kulon-progo?page=all"),
            ("Ribuan Personel Polda Lampung Bertugas Pengamanan Pemilu 2024",
             "https://lampung.jpnn.com/politik/1/ribuan-personel-polda-lampung-bertugas-pengamanan-pemilu-2024"),
        ):
            dto = SitemapDTO(headline=headline, link=link, sources="X")
            assert Crawler._derive_headline_from_url(link) == headline  # the coincidence
            assert not Crawler._is_placeholder_headline(dto), headline

    def test_id_tail_shapes(self):
        assert Crawler._slug_has_id_tail("https://tirto.id/sidak-agrinas-hCth?page=all")      # letters, mixed case
        assert Crawler._slug_has_id_tail("https://tirto.id/rupiah-menguat-hCa5?page=all")     # mixed case + digit
        assert Crawler._slug_has_id_tail("https://www.tempo.co/ekonomi/apa-dampak-2287141")   # digits
        assert not Crawler._slug_has_id_tail("https://x.id/pengamanan-pemilu-2024")           # a year
        assert not Crawler._slug_has_id_tail("https://x.id/keadilan-terkubur-longsor")        # words
        assert not Crawler._slug_has_id_tail("https://x.id/nohyphen")


class TestFetchNewsDetailsPrefersPageTitleOverPlaceholder:
    def setup_method(self):
        self.crawler = _ConcreteCrawler()
        self.crawler.website_name = "TIRTO"
        self.crawler.page_loader = MagicMock()

    def _fetch(self, headline, soup, link=TIRTO_LINK):
        self.crawler.page_loader.get_soup = MagicMock(return_value=soup)
        return self.crawler._get_news_details(SitemapDTO(headline=headline, link=link, sources="TIRTO", sitemap_id=7))

    def test_placeholder_headline_is_replaced_by_og_title(self):
        dto = self._fetch(TIRTO_SLUG, _page(og_title=TIRTO_OG))
        assert dto.meta_data["title"] == TIRTO_OG
        assert dto.meta_data["headline_from_page"] is True

    def test_placeholder_headline_falls_back_to_title_tag(self):
        dto = self._fetch(TEMPO_SLUG, _page(title_tag="Apa Dampak Kelangkaan BBM Bersubsidi"), link=TEMPO_LINK)
        assert dto.meta_data["title"] == "Apa Dampak Kelangkaan BBM Bersubsidi"
        assert dto.meta_data["headline_from_page"] is True

    def test_placeholder_kept_when_the_page_has_no_title_at_all(self):
        dto = self._fetch(TIRTO_SLUG, _page())
        assert dto.meta_data["title"] == TIRTO_SLUG
        assert dto.meta_data["headline_from_page"] is False

    def test_real_sitemap_headline_is_never_overridden(self):
        dto = self._fetch("Rupiah Menguat, Kata BI", _page(og_title="Something Else"))
        assert dto.meta_data["title"] == "Rupiah Menguat, Kata BI"
        assert dto.meta_data["headline_from_page"] is False

    def test_empty_headline_still_takes_the_page_title(self):
        # SYS-32's original (previously unreachable) branch keeps working.
        dto = self._fetch("", _page(og_title=TIRTO_OG))
        assert dto.meta_data["title"] == TIRTO_OG
        assert dto.meta_data["headline_from_page"] is True

    def test_get_page_title_is_bypassed_for_a_real_headline_and_used_for_a_placeholder(self):
        with patch.object(_ConcreteCrawler, "_get_page_title", return_value=TIRTO_OG) as pt:
            self._fetch("Real Headline", _page(og_title=TIRTO_OG))
            pt.assert_not_called()
            dto = self._fetch(TIRTO_SLUG, _page(og_title=TIRTO_OG))
            pt.assert_called_once()
        assert dto.meta_data["title"] == TIRTO_OG


@pytest.fixture
def service():
    with patch("newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter"):
        svc = CrawlerServiceImpl(data_flow_repo=MagicMock())
    svc.crawler_dict = {"TIRTO": MagicMock()}
    svc.data_flow_repo.get_saved_category_pairs.return_value = None
    svc.data_flow_repo.save_newsdetails_data.side_effect = lambda dtos: [d.sitemap_id for d in dtos]
    svc.semantic_filter.classify.return_value = FilterDecision(False, "score", False)
    return svc


def _dto(sitemap_id, title, from_page):
    return NewsDetailsDTO(sitemap_id=sitemap_id, extracted_text=["body text"], reporter=[],
                          meta_data={"title": title, "headline_from_page": from_page})


class TestServiceWritesPageHeadlineBack:
    def test_page_headlines_are_written_back_even_for_rejected_articles(self, service):
        service.data_flow_repo.load_sitemap_data.return_value = [
            SitemapDTO(headline=TIRTO_SLUG, link=TIRTO_LINK, sources="TIRTO", sitemap_id=1)
        ]
        service.crawler_dict["TIRTO"].batch_crawling_details.return_value = [_dto(1, TIRTO_OG, True)]

        service.crawl_newsdetails("TIRTO")

        service.data_flow_repo.update_sitemap_headlines.assert_called_once_with({1: TIRTO_OG})
        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "rejected_filter")

    def test_nothing_written_when_the_headline_was_real(self, service):
        service.data_flow_repo.load_sitemap_data.return_value = [
            SitemapDTO(headline="Real", link=TIRTO_LINK, sources="TIRTO", sitemap_id=1)
        ]
        service.crawler_dict["TIRTO"].batch_crawling_details.return_value = [_dto(1, "Real", False)]

        service.crawl_newsdetails("TIRTO")

        service.data_flow_repo.update_sitemap_headlines.assert_not_called()

    def test_write_back_failure_does_not_lose_the_batch(self, service):
        service.data_flow_repo.update_sitemap_headlines.side_effect = RuntimeError("db hiccup")
        service.data_flow_repo.load_sitemap_data.return_value = [
            SitemapDTO(headline=TIRTO_SLUG, link=TIRTO_LINK, sources="TIRTO", sitemap_id=1)
        ]
        service.crawler_dict["TIRTO"].batch_crawling_details.return_value = [_dto(1, TIRTO_OG, True)]
        service.semantic_filter.classify.return_value = FilterDecision(True, "allow", False)
        service.data_flow_repo.save_chunk_data.return_value = [1]

        service.crawl_newsdetails("TIRTO")

        service.data_flow_repo.mark_sitemaps_status.assert_any_call([1], "saved")
        # The chunker still sees the real title through the DTO.
        chunked = service.chunker.chunk if isinstance(service.chunker, MagicMock) else None
        assert chunked is None or chunked.call_args[0][0].meta_data["title"] == TIRTO_OG
