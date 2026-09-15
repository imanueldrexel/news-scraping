"""Tests for _parse_paragraphs() logic (inlined from backfill_chunks.py)."""
import ast, json
import pytest


def _parse_paragraphs(raw) -> list:
    """Mirrors backfill_chunks._parse_paragraphs exactly."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    for loader in (json.loads, ast.literal_eval):
        try:
            result = loader(raw)
            if isinstance(result, list):
                return [str(p) for p in result if p]
        except Exception:
            continue
    return [raw] if raw.strip() else []


class TestParseParagraphs:
    def test_PP01_list_passthrough(self):
        assert _parse_paragraphs(["a", "b", "c"]) == ["a", "b", "c"]

    def test_PP02_json_string(self):
        assert _parse_paragraphs('["a", "b", "c"]') == ["a", "b", "c"]

    def test_PP03_python_repr_string(self):
        assert _parse_paragraphs("['a', 'b', 'c']") == ["a", "b", "c"]

    def test_PP04_empty_string(self):
        assert _parse_paragraphs("") == []

    def test_PP05_whitespace_only_string(self):
        assert _parse_paragraphs("   ") == []

    def test_PP06_none(self):
        assert _parse_paragraphs(None) == []

    def test_PP07_non_string_non_list(self):
        assert _parse_paragraphs(42) == []

    def test_PP08_list_with_empty_item_filtered(self):
        assert _parse_paragraphs('["para1", "", "para3"]') == ["para1", "para3"]

    def test_PP09_plain_string_as_single_paragraph(self):
        assert _parse_paragraphs("Just a plain string") == ["Just a plain string"]

    def test_PP10_list_of_ints_cast_to_str(self):
        assert _parse_paragraphs("[1, 2, 3]") == ["1", "2", "3"]
