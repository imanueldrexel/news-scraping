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

    def test_MS04_long_then_short_stays_separate(self):
        long_p = make_words(MAX_T)
        short_p = make_words(MIN_T - 1)
        result = self.chunker._merge_short([long_p, short_p])
        assert len(result) == 2

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
        # Each pair merges to >= MIN_T, triggering flush; result is [p0+p1, p2+p3, p4]
        assert len(result) == 3
