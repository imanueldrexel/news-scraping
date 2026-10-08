"""
Tests for HierarchicalChunker private helpers: _count, _split_with_overlap, _merge_short.
The public chunk() interface is covered in tests/test_hierarchical_chunker.py.
"""
import sys, os, importlib, types
import pytest

# Import helpers directly from chunker module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "chunker",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "newscrawler", "core", "chunker.py")
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

HierarchicalChunker = _mod.HierarchicalChunker
_count = _mod._count
_split_with_overlap = _mod._split_with_overlap

MIN_T = 80
MAX_T = 450
OVERLAP = 50


def make_words(n):
    return " ".join(f"w{i}" for i in range(n))


class TestCount:
    def test_CK01_empty(self):       assert _count("") == 0
    def test_CK02_single(self):      assert _count("hello") == 1
    def test_CK03_two(self):         assert _count("hello world") == 2
    def test_CK04_extra_spaces(self):assert _count("  hello   world  ") == 2


class TestSplitWithOverlap:
    def test_SO01_exactly_max_no_split(self):
        text = make_words(MAX_T)
        chunks = _split_with_overlap(text, MAX_T, OVERLAP)
        assert len(chunks) == 1 and chunks[0] == text

    def test_SO02_one_over_max_two_chunks(self):
        words = [f"w{i}" for i in range(MAX_T + 1)]
        chunks = _split_with_overlap(" ".join(words), MAX_T, OVERLAP)
        assert len(chunks) == 2
        assert chunks[0] == " ".join(words[:MAX_T])
        assert chunks[1] == " ".join(words[MAX_T - OVERLAP:])

    def test_SO03_900_words_three_chunks(self):
        chunks = _split_with_overlap(make_words(900), MAX_T, OVERLAP)
        assert len(chunks) == 3
        assert all(_count(c) <= MAX_T for c in chunks)

    def test_SO05_small_text_returns_single_chunk(self):
        text = make_words(10)
        chunks = _split_with_overlap(text, MAX_T, OVERLAP)
        assert len(chunks) == 1

    def test_SO04_overlap_words_match(self):
        words = [f"w{i}" for i in range(MAX_T + 1)]
        chunks = _split_with_overlap(" ".join(words), MAX_T, OVERLAP)
        tail_c1 = chunks[0].split()[MAX_T - OVERLAP:]
        head_c2 = chunks[1].split()[:OVERLAP]
        assert tail_c1 == head_c2


class TestMergeShort:
    def setup_method(self):
        self.chunker = HierarchicalChunker(min_tokens=MIN_T, max_tokens=MAX_T, overlap_tokens=OVERLAP)

    def test_MS01_single_short_unchanged(self):
        short = make_words(MIN_T - 1)
        assert self.chunker._merge_short([short]) == [short]

    def test_MS02_two_shorts_merged(self):
        p1, p2 = make_words(MIN_T - 1), make_words(MIN_T - 1)
        result = self.chunker._merge_short([p1, p2])
        assert len(result) == 1 and result[0] == p1 + " " + p2

    def test_MS03_exactly_min_not_merged(self):
        exact = make_words(MIN_T)
        nxt = make_words(MIN_T)
        result = self.chunker._merge_short([exact, nxt])
        assert len(result) == 2

    def test_MS04_long_then_short_tail_merges_backward(self):
        """SYS-105 (#275): the last paragraph has nothing to merge forward into; a short one joins
        the chunk before it instead of becoming its own (a "(jon)" chunk is a search hub)."""
        long_p = make_words(MAX_T)
        short_p = make_words(MIN_T - 1)
        result = self.chunker._merge_short([long_p, short_p])
        assert result == [long_p + " " + short_p]

    def test_MS04b_long_then_long_tail_stays_separate(self):
        long_p, tail = make_words(MAX_T), make_words(MIN_T)
        assert self.chunker._merge_short([long_p, tail]) == [long_p, tail]

    def test_MS05_short_then_long_merged(self):
        short_p = make_words(MIN_T - 1)
        long_p = make_words(MAX_T)
        result = self.chunker._merge_short([short_p, long_p])
        assert len(result) == 1 and result[0] == short_p + " " + long_p

    def test_MS06_empty_list(self):
        assert self.chunker._merge_short([]) == []

    def test_MS07_five_shorts_merged_in_pairs(self):
        n = MIN_T - 1
        paras = [make_words(n) for _ in range(5)]
        result = self.chunker._merge_short(paras)
        # Each pair merges to >= MIN_T, triggering flush; the short p4 left over joins p2+p3 (SYS-105)
        assert len(result) == 2
        assert result[1] == " ".join(paras[2:])


class TestTrailingSignOff:
    """SYS-105 (#275), through the public chunk(): an article ending in a sign-off gives no
    one-word L2 chunk; the sign-off stays in the text, at the end of the last chunk."""

    @staticmethod
    def _chunk(paragraphs):
        from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
        news = NewsDetailsDTO(sitemap_id=1, extracted_text=paragraphs, reporter=[], meta_data={"title": "t"})
        chunker = HierarchicalChunker(min_tokens=MIN_T, max_tokens=MAX_T, overlap_tokens=OVERLAP)
        return [c for c in chunker.chunk(news) if c.chunk_level == 2]

    @pytest.mark.parametrize("sign_off", ["(jon)", "--", "Editor: Theresa Sandra Desfika", "( )"])
    def test_sign_off_is_not_its_own_chunk(self, sign_off):
        body = [make_words(120), make_words(100), sign_off]
        l2 = self._chunk(body)
        assert [c.token_count for c in l2] == [120, 100 + _count(sign_off)]
        assert l2[-1].text_content.endswith(sign_off) and l2[-1].is_last_chunk

    def test_a_short_article_keeps_its_one_short_chunk(self):
        l2 = self._chunk(["Rupiah ditutup menguat."])
        assert [c.text_content for c in l2] == ["Rupiah ditutup menguat."]

    def test_tail_over_max_is_split_without_a_fragment(self):
        l2 = self._chunk([make_words(MAX_T), "(jon)"])
        assert len(l2) == 2 and min(c.token_count for c in l2) > OVERLAP


class TestChunkerConfigFromEnv:
    """DBT-13 (#48): the CHUNK_* env vars reach the chunker, and an overlap >=
    max_tokens fails at construction instead of looping forever in
    _split_with_overlap."""

    def test_defaults_come_from_constants(self, monkeypatch):
        from newscrawler.core import constants
        from newscrawler.core.chunker import HierarchicalChunker
        monkeypatch.setattr(constants, "CHUNK_MIN_TOKENS", 30)
        monkeypatch.setattr(constants, "CHUNK_MAX_TOKENS", 120)
        monkeypatch.setattr(constants, "CHUNK_OVERLAP_TOKENS", 10)
        c = HierarchicalChunker()
        assert (c.min_tokens, c.max_tokens, c.overlap_tokens) == (30, 120, 10)
        # an explicit argument still wins
        assert HierarchicalChunker(max_tokens=300).max_tokens == 300

    def test_overlap_at_or_above_max_raises_instead_of_hanging(self):
        import pytest
        from newscrawler.core.chunker import HierarchicalChunker
        with pytest.raises(ValueError, match="never advance"):
            HierarchicalChunker(max_tokens=450, overlap_tokens=450)
        with pytest.raises(ValueError, match="never advance"):
            HierarchicalChunker(max_tokens=100, overlap_tokens=150)
        with pytest.raises(ValueError):
            HierarchicalChunker(min_tokens=500, max_tokens=450)
        with pytest.raises(ValueError):
            HierarchicalChunker(max_tokens=0)
        HierarchicalChunker(max_tokens=450, overlap_tokens=449)   # the edge that still advances by 1
