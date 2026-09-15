import pytest
from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO


def _make_news(paragraphs, sitemap_id=1):
    return NewsDetailsDTO(
        sitemap_id=sitemap_id,
        extracted_text=paragraphs,
        reporter=["Wartawan Test"],
        meta_data={"title": "Judul Berita Test", "posted_at": 20260521},
    )


def _make_sitemap(sitemap_id=1):
    return SitemapDTO(
        headline="Judul",
        link="https://example.com",
        sources="BISNIS",
        category="ekonomi",
        sitemap_id=sitemap_id,
    )


CHUNKER = HierarchicalChunker(min_tokens=80, max_tokens=450, overlap_tokens=50)


class TestL1Chunk:
    def test_l1_uses_first_two_paragraphs(self):
        paras = ["Para satu " * 20, "Para dua " * 20, "Para tiga " * 20]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l1 = [c for c in chunks if c.chunk_level == 1]
        assert len(l1) == 1
        assert "Para satu" in l1[0].text_content
        assert "Para dua" in l1[0].text_content
        assert "Para tiga" not in l1[0].text_content

    def test_l1_single_paragraph_article(self):
        paras = ["Hanya satu paragraf " * 10]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l1 = [c for c in chunks if c.chunk_level == 1]
        assert len(l1) == 1
        assert l1[0].is_first_chunk is True
        assert l1[0].is_last_chunk is True

    def test_l1_metadata_populated(self):
        paras = ["Para " * 30, "Para dua " * 30]
        sitemap = _make_sitemap()
        chunks = CHUNKER.chunk(_make_news(paras), sitemap)
        l1 = next(c for c in chunks if c.chunk_level == 1)
        assert l1.source == "BISNIS"
        assert l1.category == "ekonomi"
        assert l1.title == "Judul Berita Test"
        assert l1.posted_at == 20260521


class TestL2Chunks:
    def test_normal_article_produces_l2_chunks(self):
        # 5 paragraphs, each ~100 tokens → should produce multiple L2 chunks
        paras = ["Kata " * 80] * 5
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert len(l2) >= 1

    def test_chunk_total_consistent(self):
        paras = ["Kata " * 50] * 6
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        totals = {c.chunk_total for c in l2}
        assert len(totals) == 1, "All L2 chunks must agree on chunk_total"
        assert totals.pop() == len(l2)

    def test_first_and_last_flags(self):
        paras = ["Kata " * 80] * 5
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert l2[0].is_first_chunk is True
        assert l2[0].is_last_chunk is (len(l2) == 1)
        assert l2[-1].is_last_chunk is True
        assert l2[-1].is_first_chunk is (len(l2) == 1)

    def test_chunk_indexes_sequential(self):
        paras = ["Kata " * 70] * 8
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        indexes = [c.chunk_index for c in l2]
        assert indexes == list(range(len(l2)))

    def test_short_paragraphs_merged(self):
        # Each paragraph is tiny (< min_tokens=80). They should be merged together.
        short_para = "Kalimat pendek. " * 5   # ~13 tokens each
        paras = [short_para] * 10
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        # Should be fewer chunks than paragraphs due to merging
        assert len(l2) < len(paras)

    def test_long_paragraph_split_with_overlap(self):
        # Single oversized paragraph that exceeds max_tokens=450
        long_para = "Kata panjang " * 400   # ~520 tokens
        paras = [long_para]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert len(l2) >= 2, "Oversized paragraph must be split into multiple chunks"
        # Each resulting chunk should be within the max token budget
        for chunk in l2:
            assert chunk.token_count <= CHUNKER.max_tokens * 1.2  # 20% tolerance for word splitting


class TestEdgeCases:
    def test_empty_extracted_text_returns_empty(self):
        news = NewsDetailsDTO(
            sitemap_id=99,
            extracted_text=[],
            reporter=None,
            meta_data={"title": "Empty"},
        )
        chunks = CHUNKER.chunk(news)
        assert chunks == []

    def test_whitespace_only_paragraphs_filtered(self):
        paras = ["   ", "\n\n", "Ini konten nyata " * 20, "  "]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        assert len(chunks) > 0
        for c in chunks:
            assert c.text_content.strip() != ""

    def test_no_sitemap_uses_empty_source(self):
        paras = ["Teks berita " * 30]
        chunks = CHUNKER.chunk(_make_news(paras))  # no sitemap passed
        assert all(c.source == "" for c in chunks)
        assert all(c.category is None for c in chunks)

    def test_single_short_paragraph(self):
        # Article shorter than min_tokens — should still return L1 + at least 1 L2
        paras = ["Pendek."]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l1 = [c for c in chunks if c.chunk_level == 1]
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert len(l1) == 1
        assert len(l2) >= 1

class TestChunkDefaults:
    """ChunkDTO default field values: chunk_status and embedding_id."""

    def test_L1_05_l1_initial_chunk_status(self):
        paras = ["Para " * 30, "Para dua " * 30]
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l1 = next(c for c in chunks if c.chunk_level == 1)
        assert l1.chunk_status == "pending_embedding"
        assert l1.embedding_id is None

    def test_L2_07_l2_chunk_status_is_pending_embedding(self):
        paras = ["Kata " * 80] * 3
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert all(c.chunk_status == "pending_embedding" for c in l2)

    def test_L2_08_l2_embedding_id_is_none(self):
        paras = ["Kata " * 80] * 3
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert all(c.embedding_id is None for c in l2)

    def test_EC06_total_record_count_is_1_plus_l2_count(self):
        paras = ["Kata " * 80] * 4
        chunks = CHUNKER.chunk(_make_news(paras), _make_sitemap())
        l2 = [c for c in chunks if c.chunk_level == 2]
        assert len(chunks) == 1 + len(l2)
